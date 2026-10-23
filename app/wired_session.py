# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
from coupled_trial import configuration as coupled_configuration, TrialController
"""Explicit surround session with bounded startup and one HomePod owner.

Run only in an approved TV maintenance window. No pairing or credentials are
created. Existing credentials stay in their root-only file.
"""
import asyncio
import fcntl
import json
import math
import subprocess
import sqlite3
import time
from urllib.parse import quote
from pathlib import Path
from pyatv.exceptions import BlockedStateError
from startup_playback import StartupPlayback
from recovery_policy import FrontRecoveryGate
from recovery_playback import RecoveryPlayback
from control_link import read_route
from handover_policy import snapshot as playback_snapshot, resume_after_handover
import pyatv
from pyatv.const import Protocol

ROOT=Path('/opt/homeambient-plan-b')
RUNTIME=Path('/run/homeambient-plan-b')
DATABASE=Path('/var/lib/homeambient-plan-b/cache/database.db')
FRONTS='homeambient-planb-fronts.service'
SOURCE='homeambient-planb-source.service'
REAR='homeambient-planb-router.service'
from site_config import front_output_ids
EXPECTED=front_output_ids()
CONTAINER='homeambient-fronts-restored'


LAST_DIAGNOSTIC_MODE = None

def startup_trace(stage, **fields):
    """Bounded control-plane events; no payload, credentials or volume values."""
    try:
        print(json.dumps(dict(kind='startup_diagnostic', stage=stage,
                              monotonic=time.monotonic(), timestamp=time.time(),
                              **fields)), flush=True)
    except Exception:
        pass  # Diagnostic output must not change the existing control decision.


def owner_allowed(outputs, router):
    # Fail closed on empty, mixed or unknown output lists.
    return set(outputs)=={router}


def command(*args):
    return subprocess.check_output(args,text=True,stderr=subprocess.STDOUT,timeout=25)


def service(action,unit):
    began=time.monotonic()
    startup_trace('service_begin',action=action,unit=unit)
    try:
        command('systemctl',action,unit)
    except BaseException as error:
        startup_trace('service_failed',action=action,unit=unit,
                   elapsed_ms=round((time.monotonic()-began)*1000,2),
                   error_type=type(error).__name__)
        raise
    startup_trace('service_complete',action=action,unit=unit,
               elapsed_ms=round((time.monotonic()-began)*1000,2))


def api(path,data=None,method=None):
    args=['ip','netns','exec','homeambient-fronts','curl','-fsS','--max-time','3']
    if method:args+=['-X',method]
    if data is not None:args+=['-X',method or 'PUT','-H','Content-Type: application/json','--data',json.dumps(data)]
    traced = data is not None or method is not None
    operation = path.split('?',1)[0]
    began=time.monotonic()
    if traced:startup_trace('api_begin',operation=operation,method=method or 'PUT')
    try:
        body=command(*args,'http://127.0.0.1:3689/api/'+path)
        result=json.loads(body) if body else None
    except BaseException as error:
        startup_trace('api_failed',operation=operation,method=method or ('PUT' if data is not None else 'GET'),
                   elapsed_ms=round((time.monotonic()-began)*1000,2),
                   error_type=type(error).__name__)
        raise
    if traced:startup_trace('api_complete',operation=operation,method=method or 'PUT',
                         elapsed_ms=round((time.monotonic()-began)*1000,2))
    return result


def state(mode,**details):
    global LAST_DIAGNOSTIC_MODE
    if mode != LAST_DIAGNOSTIC_MODE:
        startup_trace('mode_change',mode=mode)
        LAST_DIAGNOSTIC_MODE=mode
    RUNTIME.mkdir(parents=True,exist_ok=True)
    p=RUNTIME/'session.tmp'
    p.write_text(json.dumps(dict(mode=mode,timestamp=time.time(),**details)))
    p.replace(RUNTIME/'session.json')


async def connect():
    saved=json.loads(Path('/opt/homeambient-plan-b/apple-tv.json').read_text())
    startup_trace('apple_tv_discovery_begin')
    from device_resolver import resolve
    async def scan(**kwargs):return await pyatv.scan(asyncio.get_running_loop(),**kwargs)
    config=await resolve(saved,scan,startup_trace)
    startup_trace('apple_tv_discovery_complete',found=True)
    for protocol,credential in saved['credentials'].items():
        config.set_credentials(Protocol(int(protocol)),credential)
    startup_trace('apple_tv_connect_begin')
    connection=await pyatv.connect(config,asyncio.get_running_loop())
    startup_trace('apple_tv_connect_complete')
    return connection


async def run():
    config=json.loads((ROOT/'settings.json').read_text())
    if config.get('centre_enabled') is not False:
        raise RuntimeError('The public profile requires centre_enabled=false')
    router=config.get('router_id')
    coupled=coupled_configuration()
    coupled_controller=None
    from native_master import enabled as native_enabled, NativeController
    native_mode=native_enabled()
    volume=coupled['initial_percent'] if coupled else config['front_level']
    if not config.get('maintenance_approved'):
        raise RuntimeError('Cable/TV test approval has not been recorded; refusing to start')
    if not isinstance(volume,int) or not 0<=volume<=100:
        raise RuntimeError('Front level must be 0..100')
    # Refuse parallel old/new pipelines rather than stopping a working one.
    for unit in ('shairport-sync','homeambient-rear-audio-server','homeambient-fronts-restored',
                 'homeambient-speaker-ownership','homeambient-front-delay'):
        if subprocess.run(['systemctl','is-active','--quiet',unit]).returncode==0:
            raise RuntimeError('Existing audio/control service active: '+unit)
    lock=open('/run/homeambient-speaker-control.lock','w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    RUNTIME.mkdir(parents=True,exist_ok=True)
    atv=None;previous=None;previous_volume=None;saved_levels={};front_started=False;route_requested=False;handover_confirmed=False
    startup_playback=StartupPlayback()
    try:
        state('starting')
        atv=await connect()
        if native_mode:coupled_controller=await NativeController.prepare(atv,router,startup_trace)
        previous=[d.identifier for d in atv.audio.output_devices]
        if not previous:
            raise RuntimeError('Cannot snapshot Apple TV output selection safely')
        manually_selected=router in previous
        if manually_selected:
            snapshot=json.loads((RUNTIME/'standby-normal-output.json').read_text())
            previous=snapshot['outputs']
            previous_volume=snapshot.get('volume')
        try:
            value=float(atv.audio.volume)
            if not manually_selected and math.isfinite(value) and 0<=value<=100:previous_volume=value
        except (AttributeError,TypeError,ValueError,NotImplementedError):pass
        (RUNTIME/'previous-tv-volume.json').write_text(json.dumps(previous_volume))
        (RUNTIME/'previous-outputs.json').write_text(json.dumps(previous))
        trim_dir=RUNTIME.parent/'homeambient-surround'
        trim_dir.mkdir(exist_ok=True)
        (trim_dir/'rear-trim-db').write_text(str(config.get('rear_trim_db',0.0))+'\n')
        handover_before=None
        try:
            handover_before=playback_snapshot(await asyncio.wait_for(atv.metadata.playing(),timeout=3))
        except Exception as error:
            startup_trace('handover_snapshot_unavailable',error_type=type(error).__name__)
        if manually_selected:
            from before_handover import recover
            handover_before,recovered= recover(handover_before,snapshot,
                manually_selected=True,router=router,now=time.monotonic())
            if recovered:startup_trace('handover_prior_playing_recovered',reason='fresh_normal_route_snapshot')
        handover_began=time.monotonic()
        await startup_playback.pause(atv,handover_before,startup_trace)
        (RUNTIME/'session-active').touch()
        fronts_prepared=False
        if subprocess.run(['systemctl','is-active','--quiet',FRONTS]).returncode!=0:
            with sqlite3.connect(DATABASE) as db:
                db.execute('UPDATE speakers SET selected=0')
            service('start',FRONTS);front_started=True;fronts_prepared=True
            startup_trace('front_discovery_prepared_without_selection')
        began=time.time()
        service('start',REAR)
        service('start',SOURCE)
        for _ in range(40):
            p=RUNTIME/'rear.json'
            if p.exists():
                rear=json.loads(p.read_text())
                if rear.get('error'):raise RuntimeError(rear['error'])
                if rear.get('timestamp',0)>=began and time.time()-rear['timestamp']<3:break
            await asyncio.sleep(.25)
        else:raise RuntimeError('Wired rear did not become ready')
        if not router:
            receivers=await pyatv.scan(asyncio.get_running_loop(),hosts=[config['receiver_address']],timeout=4)
            matches=[c for c in receivers if c.name=='Pi Surround']
            if len(matches)!=1:raise RuntimeError('Pi 2 receiver was not uniquely discovered')
            airplay=matches[0].get_service(Protocol.AirPlay)
            router=airplay.properties.get('psi')
            if not router:raise RuntimeError('Receiver playback identifier must be verified via /info and saved in settings')
            (RUNTIME/'router-id.json').write_text(json.dumps(router))
        route_requested=True
        actual=[d.identifier for d in atv.audio.output_devices]
        if router in actual:
            extras=[i for i in actual if i!=router]
            if extras:
                await asyncio.wait_for(atv.audio.remove_output_devices(*extras),timeout=7)
        if not owner_allowed([d.identifier for d in atv.audio.output_devices],router):
            await asyncio.wait_for(atv.audio.set_output_devices(router),timeout=5)
        for _ in range(20):
            if owner_allowed([d.identifier for d in atv.audio.output_devices],router):break
            await asyncio.sleep(.5)
        else:raise RuntimeError('Apple TV did not confirm router-only output')
        handover_confirmed=True
        # OwnTone persists speaker selection. Clear it while stopped so stale
        # selections cannot start AirPlay 1 sessions before AirPlay 2 discovery.
        if not fronts_prepared:
            if subprocess.run(['systemctl','is-active','--quiet',FRONTS]).returncode!=0:
                with sqlite3.connect(DATABASE) as db:
                    db.execute('UPDATE speakers SET selected=0')
            service('start',FRONTS);front_started=True
        startup_trace('front_discovery_wait')
        stable_since=None
        for _ in range(40):
            try:
                outputs=api('outputs')['outputs']
                ready={str(o['id']) for o in outputs if o.get('type')=='AirPlay 2'}
                if EXPECTED <= ready:
                    if stable_since is None:stable_since=time.monotonic()
                    if time.monotonic()-stable_since>=2:break
                else:stable_since=None
            except Exception:pass
            await asyncio.sleep(.5)
        else:raise RuntimeError('Both front HomePods were not discovered')
        startup_trace('front_discovery_ready',expected_outputs=len(EXPECTED))
        saved_levels={str(o['id']):o['volume'] for o in outputs if str(o['id']) in EXPECTED}
        (RUNTIME/'previous-front-levels.json').write_text(json.dumps(saved_levels))
        if native_mode:
            await coupled_controller.seed()
        if not native_mode and coupled and coupled.get('prime_native_controls') and -26.25<=float(Path('/run/homeambient-volume/airplay-db').read_text())<=0:
            from seed_command import seed,hook_is_current
            from pyatv.interface import OutputDevice
            command_path=Path('/run/homeambient-volume/airplay-db')
            def command_identity():
                st=command_path.stat()
                return (st.st_dev,st.st_ino,st.st_mtime_ns)
            async def seed_sender(value):
                await atv.audio.get(Protocol.MRP).set_volume((value+30)/30*100,
                    OutputDevice(router,volume=-1))
            from native_key_prime import prime_key
            await prime_key(atv,
                read_command=lambda:float(command_path.read_text()),
                read_identity=command_identity,
                owns_route=lambda:owner_allowed([d.identifier for d in atv.audio.output_devices],router),
                fronts_selected=lambda:any(o.get('selected') for o in api('outputs')['outputs']),
                set_command=seed_sender,trace=startup_trace)
            source_started=float(command('systemctl','show','--value','-p',
                'ExecMainStartTimestampMonotonic',SOURCE).strip())/1e6
            # A receiver can survive route changes overnight. Its old matching
            # volume hook cannot establish the new sender session's level.
            if hook_is_current('/run/homeambient-volume/commands.jsonl',max(source_started,handover_began),
                               float(command_path.read_text())):
                startup_trace('native_seed_skipped',reason='matching_hook_in_current_handover')
            else:
                await seed(atv,
                    read_command=lambda:float(command_path.read_text()),
                    read_identity=command_identity,
                    owns_route=lambda:owner_allowed([d.identifier for d in atv.audio.output_devices],router),
                    fronts_selected=lambda:any(o.get('selected') for o in api('outputs')['outputs']),
                    set_command=seed_sender,trace=startup_trace)
            startup_trace('native_prime_satisfied',reason='verified_current_handover_volume')
        if native_mode:
            volume=coupled_controller.initial_percent
        elif coupled and coupled.get('respect_saved_front_level'):
            from coupled_master import plan
            volume=plan(float(Path('/run/homeambient-volume/airplay-db').read_text()),
                anchor_command=coupled['anchor_command'],front_level=config['front_level']).homepod_percent
        # Apply the agreed test level once; never follow or reset volume sliders.
        for output in EXPECTED:api('outputs/'+output,{'volume':volume,'selected':True})
        library=api('library/files?directory=/var/lib/homeambient-plan-b/media')
        pipes=[x for x in library['tracks']['items'] if x.get('path')=='/var/lib/homeambient-plan-b/media/front.pcm']
        if len(pipes)!=1:raise RuntimeError('Front pipe was not uniquely indexed')
        front_play_began=time.monotonic()
        api('queue/items/add?uris='+quote(pipes[0]['uri'],safe='')+'&clear=true&playback=start',method='POST')
        for _ in range(20):
            player=api('player')
            if player.get('state')=='play' and player.get('item_progress_ms',0)>0:break
            await asyncio.sleep(.25)
        else:raise RuntimeError('Front PCM player did not begin playback')
        # Public profile supports the front pair and wired rears only.
        startup_trace('startup_ready')
        if native_mode:
            coupled_controller.observe_route(owner_allowed([d.identifier for d in atv.audio.output_devices],router))
            coupled_controller.start()
        elif coupled:
            coupled_controller=TrialController(api,EXPECTED,coupled,
                command_path=Path('/run/homeambient-volume/airplay-db'),trace=startup_trace,initial_percent=volume)
            coupled_controller.observe_route(owner_allowed([d.identifier for d in atv.audio.output_devices],router))
            coupled_controller.start()
        await resume_after_handover(atv,handover_before,router,
                                   began=handover_began,front_began=front_play_began,
                                   owner_check=owner_allowed,trace=startup_trace)
        startup_playback.completed=True
        attempts=0;last_retry=last_probe=0
        recovery_gate=FrontRecoveryGate()
        recovery_playback=RecoveryPlayback()
        playback_state=None;playback_observed_at=0;recovery_snapshot=None
        while True:
            now=time.monotonic()
            probe_due=now-last_probe>5
            atv,actual=await read_route(atv,connect,startup_trace,probe=False)
            if probe_due:
                # Read route via bounded reconnect even when metadata failed.
                try:
                    playing=await asyncio.wait_for(atv.metadata.playing(),timeout=5)
                except (BlockedStateError,ConnectionError,OSError,asyncio.TimeoutError):
                    playback_state=None
                    atv,actual=await read_route(atv,connect,startup_trace,probe=True)
                    playing=await asyncio.wait_for(atv.metadata.playing(),timeout=5)
                playback_state=playing.device_state.name
                recovery_snapshot=playback_snapshot(playing)
                playback_observed_at=last_probe=time.monotonic()
            if coupled_controller:
                if native_mode:coupled_controller.atv=atv
                coupled_controller.observe_route(owner_allowed(actual,router))
            if not owner_allowed(actual,router):
                if router in actual and len(set(actual))>1:
                    await asyncio.wait_for(atv.audio.remove_output_devices(router),timeout=7)
                state('normal-tv',reason='Output selection changed; releasing Pi fronts')
                return
            rear=json.loads((RUNTIME/'rear.json').read_text())
            if time.time()-rear.get('timestamp',0)>3 or rear.get('error'):
                raise RuntimeError('Wired rear health became stale or failed')
            outputs=api('outputs')['outputs']
            selected={str(o['id']) for o in outputs if o.get('selected')}
            missing=EXPECTED-selected
            front_playing=api('player').get('state')=='play'
            test_marker=RUNTIME/'front-diagnostic'
            diagnostic=test_marker.exists() and time.time()-test_marker.stat().st_mtime<60
            recovery_now=time.monotonic()
            recovery_decision=recovery_playback.update(now=recovery_now,
                healthy=not missing and front_playing,current=recovery_snapshot,
                observed_at=playback_observed_at,owns_route=owner_allowed(actual,router))
            if recovery_decision=='armed':startup_trace('front_recovery_resume_armed')
            recovery_state=playback_state
            if recovery_playback.allow_paused_repair(now=recovery_now,current=recovery_snapshot,
                observed_at=playback_observed_at,owns_route=owner_allowed(actual,router)):
                recovery_state='Playing'
            recovery_due=recovery_gate.ready(now=recovery_now,healthy=not missing and front_playing,
                playback_state=recovery_state,observed_at=playback_observed_at)
            if not diagnostic and recovery_due and now-last_retry>5:
                if attempts>=3:raise RuntimeError('Front recovery limit reached; releasing speakers')
                startup_trace('front_recovery_requested',attempt=attempts+1,missing_count=len(missing),front_playing=front_playing)
                for output in missing:api('outputs/'+output,{'selected':True})
                if not front_playing:api('player/play',method='PUT')
                attempts+=1;last_retry=now
            if recovery_decision=='resume' and not diagnostic:
                await recovery_playback.resume(atv,router,owner_allowed,startup_trace,clock=time.monotonic)
            state('front-diagnostic' if diagnostic else ('surround' if not missing and front_playing else 'recovering'),fronts_selected=len(EXPECTED&selected),front_playing=front_playing,
                  recovery_attempts=attempts,rear=rear,
                  volume_error=coupled_controller.error if coupled_controller else None,
                  volume_hold=coupled_controller.hold_reason if coupled_controller else None)
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        state('stopped',reason='Stopped by request')
        raise
    except BaseException as error:
        state('stopped',error=type(error).__name__+': '+str(error))
        raise
    finally:
        if coupled_controller:coupled_controller.stop()
        # Restore saved endpoint levels while our container is still available.
        # Do not force the Apple TV's old route over a newer user selection.
        cleanup_owns_route=False
        if front_started and atv:
            try:cleanup_owns_route=owner_allowed([d.identifier for d in atv.audio.output_devices],router)
            except Exception as error:startup_trace('cleanup_ownership_unavailable',error_type=type(error).__name__)
        if cleanup_owns_route:
            for output,level in saved_levels.items():
                try:api('outputs/'+output,{'selected':False} if native_mode else {'volume':level,'selected':False})
                except Exception:pass
        for unit in ('homeambient-planb-centre.service','homeambient-planb-centre-sender.service',FRONTS,REAR,'homeambient-planb-network.service'):
            try:service('stop',unit)
            except Exception as error:print('Cleanup failed: '+str(error),flush=True)
        (RUNTIME/'session-active').unlink(missing_ok=True)
        if atv:
            try:
                actual={d.identifier for d in atv.audio.output_devices}
                partial_handover=route_requested and not handover_confirmed and actual==set(previous or [])|{router}
                if previous and (owner_allowed(actual,router) or partial_handover):
                    await asyncio.wait_for(atv.audio.set_output_devices(*previous),timeout=8)
                    if not native_mode and previous_volume is not None and {d.identifier for d in atv.audio.output_devices}==set(previous):
                        await asyncio.wait_for(atv.audio.set_volume(previous_volume),timeout=5)
                await startup_playback.resume_failed_startup(atv,original_route=previous,
                    actual_route=[d.identifier for d in atv.audio.output_devices],trace=startup_trace)
            except Exception as error:
                startup_trace('cleanup_route_restore_unavailable',error_type=type(error).__name__)
            finally:
                tasks=atv.close()
                if tasks:await asyncio.wait_for(asyncio.gather(*tasks,return_exceptions=True),timeout=5)
        fcntl.flock(lock,fcntl.LOCK_UN);lock.close()


if __name__=='__main__':
    import signal
    async def main():
        task=asyncio.create_task(run())
        loop=asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM,task.cancel)
        loop.add_signal_handler(signal.SIGINT,task.cancel)
        try:await task
        except asyncio.CancelledError:pass
    asyncio.run(main())

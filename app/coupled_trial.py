# SPDX-License-Identifier: GPL-2.0-or-later
# Public packaging: device identities moved to site settings, 2026-10-23.
"""Opt-in shared-master integration. No flag means the current production path."""
import json,math,os,pathlib,threading,time
from coupled_master import CoupledMaster,FIXED_PROGRAMME_GAIN,FrontsUnavailable,ContextUnavailable

RUNTIME=pathlib.Path('/run/homeambient-plan-b')
FLAG=RUNTIME/'coupled-volume-trial.json'
PERSISTENT=pathlib.Path('/opt/homeambient-plan-b/linked-volume.json')
GAIN=RUNTIME/'coupled-rear-gain.json'

def configuration(path=FLAG,clock=time.time):
    try:settings=json.loads(path.read_text())
    except FileNotFoundError:
        if path!=FLAG:return None
        try:settings=json.loads(PERSISTENT.read_text())
        except FileNotFoundError:return None
    persistent=settings.get('kind')=='coupled-master-persistent-v1'
    if persistent:
        if (settings.get('fixed_programme_gain')!=FIXED_PROGRAMME_GAIN or settings.get('initial_percent')!=60
                or settings.get('ceiling')!=100 or not -28.125<=float(settings.get('anchor_command',0))<=-20
                or settings.get('respect_saved_front_level') is not True or settings.get('persistent_volume_api') is not True):
            raise ValueError('Invalid persistent linked-volume configuration')
        return dict(settings,expires=None)
    pilot=settings.get('kind')=='coupled-master-pilot-v1'
    if (settings.get('kind') not in ['coupled-master-v1','coupled-master-pilot-v1']
            or not isinstance(settings.get('expires'),(int,float))
            or not math.isfinite(settings['expires'])
            or not 0<settings['expires']-clock()<=(1800 if pilot else 300)
            or settings.get('fixed_programme_gain')!=FIXED_PROGRAMME_GAIN
            or settings.get('initial_percent')!=60
            or settings.get('ceiling')!=(100 if pilot else 60)
            or not -28.125<=float(settings.get('anchor_command',-26.25))<=-20):
        raise ValueError('Invalid or expired coupled-volume trial')
    return settings

def render_gain(path=GAIN,clock=time.time):
    """Audio-worker read: missing, stale or malformed state means quiet rear."""
    try:
        state=json.loads(path.read_text());age=clock()-state['timestamp']
        gain=float(state['gain'])
        if 0<=age<2 and math.isfinite(gain) and 0<=gain<=1:return gain
    except (OSError,ValueError,TypeError,KeyError):pass
    return 0.

class TrialController:
    def __init__(self,api,front_ids,settings,*,command_path,trace,
                 gain_path=GAIN,rear_path=RUNTIME/'rear.json',clock=time.time,initial_percent=None,front_settings_path=pathlib.Path('/opt/homeambient-plan-b/settings.json')):
        self.settings=settings;self.command_path=pathlib.Path(command_path)
        self.trace=trace;self.gain_path=gain_path;self.rear_path=rear_path
        self.clock=clock;self.stopped=threading.Event();self.thread=None
        self.owned=False;self.ownership_time=0.;self.last_command=None
        self.current_gain=0.;self.error=None
        self.hold_reason=None;self.hold_since=None;self.hold_gain=0.
        self.saved_front=None;self.reconcile_until=0.
        if settings.get('respect_saved_front_level'):
            from saved_front_level import SavedFrontLevel
            self.saved_front=SavedFrontLevel(front_settings_path)
        front_level=self.saved_front.level if self.saved_front else 100
        initial_percent=initial_percent if initial_percent is not None else max(0,settings['initial_percent']+front_level-100)
        self.volume_api=None
        if settings.get('persistent_volume_api'):
            from thread_volume_api import ThreadVolumeAPI
            self.volume_api=ThreadVolumeAPI(front_ids)
        self.owner=CoupledMaster(self.volume_api or api,front_ids,self,initial_percent=initial_percent,
            route_owned=self.route_owned,rear_fresh=self.rear_fresh,trial_ceiling=settings['ceiling'],
            anchor_command=settings.get('anchor_command',-26.25),front_level=front_level)

    def observe_route(self,owned):
        self.owned=bool(owned);self.ownership_time=self.clock()

    def route_owned(self):return self.owned and 0<=self.clock()-self.ownership_time<3

    def rear_fresh(self):
        try:
            s=json.loads(self.rear_path.read_text())
            return 0<=self.clock()-s['timestamp']<3 and s.get('error') is None
        except (OSError,ValueError,KeyError,TypeError):return False

    def set_gain(self,gain):
        self.current_gain=gain
        tmp=self.gain_path.with_suffix('.gain-tmp')
        tmp.write_text(json.dumps({'gain':gain,'timestamp':self.clock()}))
        os.chmod(tmp,0o644);os.replace(tmp,self.gain_path)

    def tick(self):
        if self.error:
            self.set_gain(0.);return
        try:
            if self.hold_reason:
                command=float(self.command_path.read_text())
                if command in (-144.,-30.):self.hold_gain=0.
                if not self.route_owned() or not self.rear_fresh():
                    self.hold_since=None;self.set_gain(0.);return
                try:self.owner._verify(self.owner.percent,preflight=True)
                except FrontsUnavailable:
                    self.hold_since=None;self.set_gain(self.hold_gain);return
                except ContextUnavailable:
                    self.hold_since=None;self.set_gain(0.);return
                if self.hold_since is None:self.hold_since=self.clock()
                age=self.clock()-self.hold_since
                if not .5<=age<3:
                    if age<0 or age>=3:self.hold_since=self.clock()
                    self.set_gain(self.hold_gain);return
                self.trace('coupled_volume_revalidated',reason=self.hold_reason)
                self.hold_reason=None;self.hold_since=None
                self.last_command=None # Apply only the latest pending intent.
            if self.settings.get('expires') is not None and self.clock()>=self.settings['expires']:
                raise RuntimeError('Trial expired; supervisor must restore baseline')
            command=float(self.command_path.read_text())
            if self.saved_front:
                changed=self.saved_front.poll()
                if changed is not None:
                    self.reconcile_until=self.clock()+10
                    self.trace('linked_front_level_observed',front_level=changed)
                if self.clock()<self.reconcile_until:
                    proposed=self.owner.reconcile_saved_level(command,self.saved_front.level)
                    self.last_command=command;self.current_gain=proposed.rear_gain
                    self.set_gain(self.current_gain);return
            if command!=self.last_command:
                began=time.monotonic()
                self.trace('coupled_volume_begin',source_command=command)
                selected=self.owner.apply(command);self.last_command=command
                self.trace('coupled_volume_applied',source_command=command,
                    homepod_percent=selected.homepod_percent,rear_gain=selected.rear_gain,
                    elapsed_ms=round((time.monotonic()-began)*1000,3))
            else:
                # Refresh health/ownership even when no button was pressed.
                if not self.route_owned() or not self.rear_fresh():
                    raise ContextUnavailable('Trial route or rear freshness lost')
                self.set_gain(self.current_gain)
        except (FrontsUnavailable,ContextUnavailable) as error:
            if self.hold_reason is None:
                self.hold_gain=self.current_gain
                self.trace('coupled_volume_deferred',reason=type(error).__name__+': '+str(error))
            self.hold_reason=type(error).__name__;self.hold_since=None
            if float(self.command_path.read_text()) in (-144.,-30.):self.hold_gain=0.
            self.set_gain(self.hold_gain if isinstance(error,FrontsUnavailable) else 0.)
        except Exception as error:
            self.error=type(error).__name__+': '+str(error)
            self.set_gain(0.);self.trace('coupled_volume_fault',reason=self.error)

    def start(self):
        self.set_gain(0.)
        self.thread=threading.Thread(target=self.run,name='coupled-master',daemon=True)
        self.thread.start()

    def run(self):
        while not self.stopped.is_set():
            self.tick();self.stopped.wait(.1)

    def stop(self):
        self.stopped.set()
        if self.thread:self.thread.join(timeout=10)
        if self.volume_api:self.volume_api.close()
        self.set_gain(0.)

class GainReader:
    """Read IPC away from the audio thread; stale reader state means silence."""
    def __init__(self,read=render_gain,clock=time.monotonic):
        self.read=read;self.clock=clock;self.value=(0.,float('-inf'))
        self.stopped=threading.Event();self.thread=None
    def poll(self):self.value=(self.read(),self.clock())
    def gain(self):
        value,when=self.value
        return value if 0<=self.clock()-when<.5 else 0.
    def start(self):
        self.poll()
        self.thread=threading.Thread(target=self.run,name='render-gain-reader',daemon=True)
        self.thread.start()
    def run(self):
        while not self.stopped.wait(.05):self.poll()
    def stop(self):
        self.stopped.set()
        if self.thread:self.thread.join(timeout=1)

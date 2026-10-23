/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <stdint.h>
#include <stddef.h>
#include <math.h>
#include <string.h>
struct gain_state { double current, target; uint32_t remaining; };
void late_gain(const int16_t *in, int16_t *out, size_t frames, struct gain_state *s) {
  const size_t n=frames<s->remaining?frames:s->remaining;
  const double base=s->current;
  const double step=s->remaining?(s->target-base)/s->remaining:0.;
  if (!n && s->target==0.) { memset(out,0,frames*4);s->current=0.;return; }
  for (size_t i=0;i<frames;i++) {
    const double g=i<n?base+step*(i+1):s->target;
    out[2*i]=(int16_t)lrint((double)in[2*i]*g);
    out[2*i+1]=(int16_t)lrint((double)in[2*i+1]*g);
  }
  if(n) {s->current=base+step*n;s->remaining-=n;}
  if(!s->remaining)s->current=s->target;
}

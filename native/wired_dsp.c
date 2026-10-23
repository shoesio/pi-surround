/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <stdint.h>
#include <stddef.h>
#include <math.h>
static int16_t sample(double x) {
    double y=nearbyint(x);
    if(y>32767) y=32767;
    if(y< -32768) y=-32768;
    return (int16_t)y;
}
static double corr(const int16_t *p,size_t n,int a,int b) {
    double sx=0,sy=0,sxx=0,syy=0,sxy=0;
    for(size_t i=0;i<n;i++){double x=p[i*8+a],y=p[i*8+b];sx+=x;sy+=y;sxx+=x*x;syy+=y*y;sxy+=x*y;}
    if(!n || sxx/n<22500 || syy/n<22500) return 0;
    double xx=sxx-sx*sx/n,yy=syy-sy*sy/n;
    double denom=sqrt(fmax(0,xx)*fmax(0,yy));
    return denom<1 ? 0 : (sxy-sx*sy/n)/denom;
}
void ha_mix(const int16_t *p,size_t n,double centre_gain,double lfe_gain,double gain,double rear_db,int16_t *front,int16_t *rear) {
    int duplicate=corr(p,n,0,6)>.995 && corr(p,n,1,7)>.995;
    double rear_gain=pow(10,rear_db/20);
    for(size_t i=0;i<n;i++){
        int32_t fl=(int32_t)nearbyint(p[i*8]*gain),fr=(int32_t)nearbyint(p[i*8+1]*gain);
        int32_t fc=(int32_t)nearbyint(p[i*8+2]*gain),lf=(int32_t)nearbyint(p[i*8+3]*gain);
        double rl,rr;
        if(duplicate){front[i*2]=sample(fl);front[i*2+1]=sample(fr);}
        else {
            int32_t centre=(int32_t)nearbyint(fc*centre_gain),lfe=(int32_t)nearbyint(lf*lfe_gain);
            front[i*2]=sample(2.0*(fl+centre+nearbyint(lfe*1.5)));
            front[i*2+1]=sample(2.0*(fr+centre+nearbyint(lfe*1.5)));
        }
        /* SL/SR already contain the receiver's rear bus. Correlation with
         * fronts is not a reliable indication of UI audio: quiet ambience
         * can cross that classifier and must retain the same rear gain. */
        rl=(p[i*8+6]*gain)*rear_gain+lf*lfe_gain*.25;
        rr=(p[i*8+7]*gain)*rear_gain+lf*lfe_gain*.25;
        rear[i*2]=sample(rl/(1+fabs(rl)/32767));rear[i*2+1]=sample(rr/(1+fabs(rr)/32767));
    }
}
void ha_interp(const double *p,int capacity,int head,int count,double phase,double ratio,int16_t *out) {
    for(int i=0;i<count;i++){
        double pos=phase+i*ratio;int whole=(int)pos;double frac=pos-whole;
        int a=(head+whole)%capacity,b=(a+1)%capacity;
        for(int c=0;c<2;c++){double x=p[a*2+c],y=p[b*2+c];out[i*2+c]=sample(x+(y-x)*frac);}
    }
}

/* Optional centre bus. Original ha_mix stays byte-for-byte unchanged when off. */
void ha_mix3(const int16_t *p,size_t n,double centre_gain,double lfe_gain,double gain,double rear_db,double centre_db,int16_t *front,int16_t *rear,int16_t *centre) {
    ha_mix(p,n,0,lfe_gain,gain,rear_db,front,rear);
    int duplicate=corr(p,n,0,6)>.995 && corr(p,n,1,7)>.995;
    double trim=pow(10,centre_db/20);
    for(size_t i=0;i<n;i++) {
        int32_t fc=(int32_t)nearbyint(p[i*8+2]*gain);
        double v=duplicate ? 0 : 2.0*nearbyint(fc*centre_gain)*trim;
        centre[i*2]=centre[i*2+1]=sample(v);
    }
}

/* Diagnostic arithmetic only; original mixer/interpolator above unchanged. */
void ha_probe(const int16_t *p,size_t n,double *out) {
    for(int ch=0;ch<8;ch++) {
        double sum=0;for(size_t i=0;i<n;i++){double x=p[i*8+ch];sum+=x*x;}
        out[ch]=n?sqrt(sum/n):0;
    }
    out[8]=corr(p,n,0,6);out[9]=corr(p,n,1,7);
    int exact=n>0,varl=0,varr=0;
    for(size_t i=0;i<n;i++) {
        if(p[i*8]!=p[i*8+6] || p[i*8+1]!=p[i*8+7])exact=0;
        if(p[i*8]!=p[0])varl=1;
        if(p[i*8+1]!=p[1])varr=1;
    }
    out[10]=exact && varl && varr;
    out[11]=(out[8]>.995 && out[9]>.995);
}

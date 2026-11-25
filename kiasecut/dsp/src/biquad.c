#include "kcdsp.h"

kc_coef kc_biquad(int kind, double sr, double freq, double q, double gain_db) {
    kc_coef c = {1.0, 0.0, 0.0, 0.0, 0.0};
    if (kind == KC_BQ_OFF)
        return c;
    freq = kc_clamp(freq, 10.0, sr * 0.49);
    q = kc_clamp(q, 0.05, 40.0);
    double w = 2.0 * KC_PI * freq / sr, cw = cos(w), sw = sin(w), alpha = sw / (2.0 * q);
    double A = pow(10.0, gain_db / 40.0), sa = 2.0 * sqrt(A) * alpha;
    double b0, b1, b2, a0, a1, a2;
    switch (kind) {
    case KC_BQ_BELL:
        b0 = 1 + alpha * A; b1 = -2 * cw; b2 = 1 - alpha * A;
        a0 = 1 + alpha / A; a1 = -2 * cw; a2 = 1 - alpha / A;
        break;
    case KC_BQ_LOWSHELF:
        b0 = A * ((A + 1) - (A - 1) * cw + sa); b1 = 2 * A * ((A - 1) - (A + 1) * cw); b2 = A * ((A + 1) - (A - 1) * cw - sa);
        a0 = (A + 1) + (A - 1) * cw + sa; a1 = -2 * ((A - 1) + (A + 1) * cw); a2 = (A + 1) + (A - 1) * cw - sa;
        break;
    case KC_BQ_HIGHSHELF:
        b0 = A * ((A + 1) + (A - 1) * cw + sa); b1 = -2 * A * ((A - 1) + (A + 1) * cw); b2 = A * ((A + 1) + (A - 1) * cw - sa);
        a0 = (A + 1) - (A - 1) * cw + sa; a1 = 2 * ((A - 1) - (A + 1) * cw); a2 = (A + 1) - (A - 1) * cw - sa;
        break;
    case KC_BQ_LOWCUT:                          /* a high pass */
        b0 = (1 + cw) / 2; b1 = -(1 + cw); b2 = (1 + cw) / 2;
        a0 = 1 + alpha; a1 = -2 * cw; a2 = 1 - alpha;
        break;
    case KC_BQ_HIGHCUT:                         /* a low pass */
        b0 = (1 - cw) / 2; b1 = 1 - cw; b2 = (1 - cw) / 2;
        a0 = 1 + alpha; a1 = -2 * cw; a2 = 1 - alpha;
        break;
    case KC_BQ_NOTCH:
        b0 = 1; b1 = -2 * cw; b2 = 1;
        a0 = 1 + alpha; a1 = -2 * cw; a2 = 1 - alpha;
        break;
    case KC_BQ_BANDPASS:                        /* 0 dB at its centre */
        b0 = alpha; b1 = 0; b2 = -alpha;
        a0 = 1 + alpha; a1 = -2 * cw; a2 = 1 - alpha;
        break;
    default:                                    /* KC_BQ_ALLPASS */
        b0 = 1 - alpha; b1 = -2 * cw; b2 = 1 + alpha;
        a0 = 1 + alpha; a1 = -2 * cw; a2 = 1 - alpha;
        break;
    }
    c.b0 = b0 / a0; c.b1 = b1 / a0; c.b2 = b2 / a0; c.a1 = a1 / a0; c.a2 = a2 / a0;
    return c;
}

/* The coefficients move in a straight line: any point between two stable filters is stable
 * (their a1, a2 lie in a triangle), so no step of the way can run away. */
void kc_biquad_run(kc_bqstate *s, const kc_coef *from, const kc_coef *to, const float *in, float *out, int n) {
    kc_coef c = *from;
    double k = n > 0 ? 1.0 / n : 0.0;
    double d0 = (to->b0 - c.b0) * k, d1 = (to->b1 - c.b1) * k, d2 = (to->b2 - c.b2) * k;
    double e1 = (to->a1 - c.a1) * k, e2 = (to->a2 - c.a2) * k;
    for (int i = 0; i < n; i++) {
        c.b0 += d0; c.b1 += d1; c.b2 += d2; c.a1 += e1; c.a2 += e2;
        for (int ch = 0; ch < 2; ch++) {
            double x = in[2 * i + ch];
            double y = c.b0 * x + s->z1[ch];
            s->z1[ch] = c.b1 * x - c.a1 * y + s->z2[ch];
            s->z2[ch] = c.b2 * x - c.a2 * y;
            out[2 * i + ch] = (float)y;
        }
    }
    for (int ch = 0; ch < 2; ch++) {
        s->z1[ch] = kc_flush(s->z1[ch]);
        s->z2[ch] = kc_flush(s->z2[ch]);
    }
}

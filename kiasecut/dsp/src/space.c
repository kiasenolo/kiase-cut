/* 混響, 延遲, 立體寬度, 左右平衡, 左右交換, 反相, 單聲道. */
#include "kcdsp.h"

/* -- stereo tools: out = a 2 x 2 matrix of in, moved to its new values across the block --------- */
typedef struct { double m[4]; } matrix_state;

static void matrix_run(kc_fx *f, const double to[4], const float *in, float *out, int n) {
    matrix_state *s = f->state;
    double m[4], d[4];
    for (int k = 0; k < 4; k++) {
        if (f->fresh)
            s->m[k] = to[k];
        m[k] = s->m[k];
        d[k] = (to[k] - m[k]) / n;
        s->m[k] = to[k];
    }
    for (int i = 0; i < n; i++) {
        double l = in[2 * i], r = in[2 * i + 1];
        for (int k = 0; k < 4; k++)
            m[k] += d[k];
        out[2 * i] = (float)(m[0] * l + m[1] * r);
        out[2 * i + 1] = (float)(m[2] * l + m[3] * r);
    }
}

static void matrix_reset(kc_fx *f) { memset(f->state, 0, sizeof(matrix_state)); }

#define MATRIX_EFFECT(id, params_, defaults_, count, ...)                                                      \
    static void id##_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {   \
        (void)side; (void)pos;                                                                                 \
        __VA_ARGS__;                                                                                           \
        matrix_run(f, to, in, out, n);                                                                         \
    }                                                                                                          \
    const kc_type kc_##id##_type = {#id, count, params_, defaults_, sizeof(matrix_state), 0, matrix_reset,     \
                                    id##_process, 0, 0, 0, 0};

static const char *const none_p[] = {""};
static const double none_d[] = {0};
static const char *const width_p[] = {"width"};
static const double width_d[] = {100};
static const char *const bal_p[] = {"bal"};
static const double bal_d[] = {0};
static const char *const inv_p[] = {"l", "r"};
static const double inv_d[] = {0, 0};

/* width: the middle kept, the difference between the sides scaled */
MATRIX_EFFECT(width, width_p, width_d, 1,
              double w = kc_clamp(f->p[0], 0, 200) / 100.0; double to[4] = {(1 + w) / 2, (1 - w) / 2, (1 - w) / 2, (1 + w) / 2})
MATRIX_EFFECT(balance, bal_p, bal_d, 1,
              double b = kc_clamp(f->p[0], -100, 100) / 100.0; double to[4] = {b > 0 ? 1 - b : 1, 0, 0, b < 0 ? 1 + b : 1})
MATRIX_EFFECT(swap, none_p, none_d, 0, double to[4] = {0, 1, 1, 0})
MATRIX_EFFECT(mono, none_p, none_d, 0, double to[4] = {0.5, 0.5, 0.5, 0.5})
MATRIX_EFFECT(invert, inv_p, inv_d, 2, double to[4] = {f->p[0] > 0.5 ? -1.0 : 1.0, 0, 0, f->p[1] > 0.5 ? -1.0 : 1.0})

/* a delay line read between samples; len: a power of two */
static inline double line_read(const float *buf, int mask, int64_t w, double back) {
    double at = (double)w - back;
    int64_t i = (int64_t)floor(at);
    double frac = at - (double)i;
    return buf[i & mask] * (1 - frac) + buf[(i + 1) & mask] * frac;
}

/* -- delay: time, feedback, mix ----------------------------------------------------------------- */
#define DL_LEN (1 << 17)                /* 2.7 s at 48 kHz */
typedef struct { float *buf[2]; int64_t w; double time, fb, mix; } delay_state;
static const char *const delay_p[] = {"ms", "fb", "mix"};
static const double delay_d[] = {250, 30, 35};

static int delay_init(kc_fx *f) {
    delay_state *s = f->state;
    for (int c = 0; c < 2; c++)
        if (!(s->buf[c] = calloc(DL_LEN, sizeof(float))))
            return 0;
    return 1;
}

static void delay_destroy(kc_fx *f) {
    delay_state *s = f->state;
    free(s->buf[0]);
    free(s->buf[1]);
}

static void delay_reset(kc_fx *f) {
    delay_state *s = f->state;
    for (int c = 0; c < 2; c++)
        if (s->buf[c])
            memset(s->buf[c], 0, DL_LEN * sizeof(float));
    s->w = DL_LEN;
}

static void delay_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    delay_state *s = f->state;
    double time = kc_clamp(f->p[0] * 0.001 * f->sr, 1.0, DL_LEN - 4);
    double fb = kc_clamp(f->p[1], 0, 95) / 100.0, mix = kc_clamp(f->p[2], 0, 100) / 100.0;
    (void)side; (void)pos;
    if (f->fresh) {
        s->time = time;
        s->fb = fb;
        s->mix = mix;
    }
    double dfb = (fb - s->fb) / n, dmix = (mix - s->mix) / n;
    double glide = 1.0 - exp(-1.0 / (0.05 * f->sr));     /* a new time is slid to, as tape would */
    for (int i = 0; i < n; i++) {
        s->time += (time - s->time) * glide;
        if (fabs(time - s->time) < 1e-3)
            s->time = time;
        s->fb += dfb;
        s->mix += dmix;
        for (int c = 0; c < 2; c++) {
            double x = in[2 * i + c];
            double y = line_read(s->buf[c], DL_LEN - 1, s->w, s->time);
            s->buf[c][s->w & (DL_LEN - 1)] = (float)kc_flush(x + y * s->fb);
            out[2 * i + c] = (float)(x * (1 - s->mix) + y * s->mix);
        }
        s->w++;
    }
    s->fb = fb;
    s->mix = mix;
}

/* until the echoes are 90 dB down */
static double delay_tail(const kc_fx *f) {
    double t = kc_clamp(f->p[0], 0, 2700) / 1000.0, fb = kc_clamp(f->p[1], 0, 95) / 100.0;
    double echoes = fb > 0.001 ? ceil(log(3e-5) / log(fb)) + 1 : 1;
    return kc_clamp(t * echoes, 0.0, 30.0);
}

const kc_type kc_delay_type = {"delay", 3, delay_p, delay_d, sizeof(delay_state), delay_init, delay_reset,
                               delay_process, 0, delay_tail, delay_destroy, 0};

/* -- reverb: a pre-delay, a few all-passes to smear the attack, then eight delay lines feeding
 * each other through a Hadamard matrix, each losing what makes the whole die away in the
 * decay time, the highs sooner than the lows -------------------------------------------------- */
#define RV_LINES 8
#define RV_LEN (1 << 14)
#define RV_PRE (1 << 15)
#define RV_AP 4
#define RV_AP_LEN 1024
static const int rv_base[RV_LINES] = {1423, 1777, 2137, 2473, 2833, 3209, 3571, 3943};
static const int rv_ap[2][RV_AP] = {{142, 107, 379, 277}, {151, 113, 401, 263}};

typedef struct {
    float *line[RV_LINES], *pre[2], *ap[2][RV_AP];
    double lp[RV_LINES], len[RV_LINES], gain[RV_LINES];
    double wet, dry, predelay, damp;
    int64_t w;
} reverb_state;

static const char *const reverb_p[] = {"decay", "room", "wet", "dry", "pre", "damp"};
static const double reverb_d[] = {1.5, 2.0, 25, 100, 0, 6500};

static void reverb_destroy(kc_fx *f) {
    reverb_state *s = f->state;
    for (int k = 0; k < RV_LINES; k++)
        free(s->line[k]);
    for (int c = 0; c < 2; c++) {
        free(s->pre[c]);
        for (int a = 0; a < RV_AP; a++)
            free(s->ap[c][a]);
    }
}

static int reverb_init(kc_fx *f) {
    reverb_state *s = f->state;
    int ok = 1;
    for (int k = 0; k < RV_LINES; k++)
        ok &= (s->line[k] = calloc(RV_LEN, sizeof(float))) != 0;
    for (int c = 0; c < 2; c++) {
        ok &= (s->pre[c] = calloc(RV_PRE, sizeof(float))) != 0;
        for (int a = 0; a < RV_AP; a++)
            ok &= (s->ap[c][a] = calloc(RV_AP_LEN, sizeof(float))) != 0;
    }
    return ok;
}

static void reverb_reset(kc_fx *f) {
    reverb_state *s = f->state;
    for (int k = 0; k < RV_LINES; k++) {
        if (s->line[k])
            memset(s->line[k], 0, RV_LEN * sizeof(float));
        s->lp[k] = 0;
    }
    for (int c = 0; c < 2; c++) {
        if (s->pre[c])
            memset(s->pre[c], 0, RV_PRE * sizeof(float));
        for (int a = 0; a < RV_AP; a++)
            if (s->ap[c][a])
                memset(s->ap[c][a], 0, RV_AP_LEN * sizeof(float));
    }
    s->w = RV_PRE;
}

static void reverb_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    reverb_state *s = f->state;
    double decay = kc_clamp(f->p[0], 0.1, 20.0), scale = 0.45 + 0.27 * kc_clamp(f->p[1], 0.0, 5.0);
    double wet = kc_clamp(f->p[2], 0, 100) / 100.0, dry = kc_clamp(f->p[3], 0, 100) / 100.0;
    double predelay = kc_clamp(f->p[4], 0, 500) * 0.001 * f->sr;
    double damp = exp(-2.0 * KC_PI * kc_clamp(f->p[5], 500, 20000) / f->sr);
    double len[RV_LINES], gain[RV_LINES];
    (void)side; (void)pos;
    for (int k = 0; k < RV_LINES; k++) {
        len[k] = rv_base[k] * scale * f->sr / 48000.0;
        if (len[k] > RV_LEN - 4)
            len[k] = RV_LEN - 4;
        gain[k] = pow(10.0, -3.0 * len[k] / (decay * f->sr));       /* 60 dB down in `decay` s */
    }
    if (f->fresh) {
        memcpy(s->len, len, sizeof len);
        memcpy(s->gain, gain, sizeof gain);
        s->wet = wet;
        s->dry = dry;
        s->predelay = predelay;
    }
    double dwet = (wet - s->wet) / n, ddry = (dry - s->dry) / n;
    double glide = 1.0 - exp(-1.0 / (0.08 * f->sr));
    memcpy(s->gain, gain, sizeof gain);
    for (int i = 0; i < n; i++) {
        double l = in[2 * i], r = in[2 * i + 1], feed[2] = {l, r};
        s->wet += dwet;
        s->dry += ddry;
        s->predelay += (predelay - s->predelay) * glide;
        for (int c = 0; c < 2; c++) {
            s->pre[c][s->w & (RV_PRE - 1)] = (float)feed[c];
            double v = line_read(s->pre[c], RV_PRE - 1, s->w, s->predelay);
            for (int a = 0; a < RV_AP; a++) {
                int at = (int)(s->w % rv_ap[c][a]);
                double held = s->ap[c][a][at];
                double y = held - 0.62 * v;
                s->ap[c][a][at] = (float)kc_flush(v + 0.62 * y);
                v = y;
            }
            feed[c] = v;
        }
        double y[RV_LINES];
        for (int k = 0; k < RV_LINES; k++) {
            s->len[k] += (len[k] - s->len[k]) * glide;
            double v = line_read(s->line[k], RV_LEN - 1, s->w, s->len[k]);
            s->lp[k] = kc_flush(v + (s->lp[k] - v) * damp);
            y[k] = s->lp[k] * s->gain[k];
        }
        double outl = y[0] - y[2] + y[4] - y[6], outr = y[1] - y[3] + y[5] - y[7];
        for (int step = 1; step < RV_LINES; step *= 2)             /* the Hadamard matrix */
            for (int a = 0; a < RV_LINES; a += 2 * step)
                for (int b = a; b < a + step; b++) {
                    double u = y[b], v = y[b + step];
                    y[b] = u + v;
                    y[b + step] = u - v;
                }
        for (int k = 0; k < RV_LINES; k++)
            s->line[k][s->w & (RV_LEN - 1)] = (float)kc_flush(y[k] * 0.35355339059327373 + feed[k & 1] * 0.35);
        out[2 * i] = (float)(l * s->dry + outl * s->wet);
        out[2 * i + 1] = (float)(r * s->dry + outr * s->wet);
        s->w++;
    }
    s->wet = wet;
    s->dry = dry;
}

static double reverb_tail(const kc_fx *f) {
    return kc_clamp(1.5 * kc_clamp(f->p[0], 0.1, 20.0) + f->p[4] / 1000.0, 0.1, 30.0);
}

const kc_type kc_reverb_type = {"reverb", 6, reverb_p, reverb_d, sizeof(reverb_state), reverb_init, reverb_reset,
                                reverb_process, 0, reverb_tail, reverb_destroy, 0};

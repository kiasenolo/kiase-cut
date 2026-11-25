/* 壓縮器, 限幅器, 噪音閘, 擴展器, 硬限幅.
 *
 * All of them are linked in stereo: one gain for both sides, from the louder one. The
 * compressor, gate and expander can listen to a side-chain instead of what they work on.
 * Their meters: [0] the loudest the detector heard in the block, [1] the loudest that came
 * out (both linear), [2] the most the gain was turned down, in dB (a positive number).
 * Their response is the curve at rest: the level out (dB) for a level in (dB), in place of
 * the frequency. */
#include "kcdsp.h"

/* a one-pole step per sample reaching 63 % in ms */
static double pole(double ms, double sr) { return exp(-1.0 / (kc_clamp(ms, 0.01, 60000.0) * 0.001 * sr)); }

typedef struct {
    double det;             /* the detector: the peak, let go over a few milliseconds */
    double gain_db;         /* the gain being applied */
    double pre, post;       /* the gains before and after, as last block ended */
    long hold;              /* gate: samples it still stays open */
    int open;
} dyn_state;

static void dyn_reset(kc_fx *f) { memset(f->state, 0, sizeof(dyn_state)); }

static inline double detect(dyn_state *s, const float *x, int i, double scale, double keep) {
    double a = fabsf(x[2 * i]), b = fabsf(x[2 * i + 1]);
    double v = (a > b ? a : b) * scale;
    s->det = v > s->det * keep ? v : kc_flush(s->det * keep);
    return s->det;
}

static void note(kc_fx *f, double in, double out, double down) {
    f->meters[0] = (float)in;
    f->meters[1] = (float)out;
    f->meters[2] = (float)down;
}

/* -- compressor: pre gain, threshold, ratio, attack, release, knee, make up --------------------- */
static const char *const comp_params[] = {"gain", "thr", "ratio", "at", "rt", "knee", "mk"};
static const double comp_defaults[] = {0, -18, 4, 20, 100, 6, 0};

static double comp_gain(double in_db, double thr, double ratio, double knee) {
    double over = in_db - thr, slope = 1.0 / kc_clamp(ratio, 1.0, 100.0) - 1.0;
    if (knee > 0.0 && fabs(over) < knee / 2)
        return slope * (over + knee / 2) * (over + knee / 2) / (2 * knee);
    return over > 0.0 ? slope * over : 0.0;
}

static void comp_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    dyn_state *s = f->state;
    double pre = kc_db_lin(f->p[0]), post = kc_db_lin(f->p[6]);
    double ka = pole(f->p[3], f->sr), kr = pole(f->p[4], f->sr), keep = pole(8.0, f->sr);
    double loud = 0, made = 0, down = 0;
    (void)pos;
    if (f->fresh) {
        s->pre = pre;
        s->post = post;
    }
    double dpre = (pre - s->pre) / n, dpost = (post - s->post) / n;
    for (int i = 0; i < n; i++) {
        s->pre += dpre;
        s->post += dpost;
        /* the threshold is of the level after the pre gain; a side-chain is heard as it is */
        double level = detect(s, side ? side : in, i, side ? 1.0 : s->pre, keep);
        double want = comp_gain(kc_lin_db(level), f->p[1], f->p[2], f->p[5]);
        double k = want < s->gain_db ? ka : kr;
        s->gain_db = kc_flush(want + (s->gain_db - want) * k);
        double g = s->pre * s->post * kc_db_lin(s->gain_db);
        float l = (float)(in[2 * i] * g), r = (float)(in[2 * i + 1] * g);
        out[2 * i] = l;
        out[2 * i + 1] = r;
        if (level > loud) loud = level;
        if (fabsf(l) > made) made = fabsf(l);
        if (fabsf(r) > made) made = fabsf(r);
        if (-s->gain_db > down) down = -s->gain_db;
    }
    s->pre = pre;
    s->post = post;
    note(f, loud, made, down);
}

static double comp_response(const kc_fx *f, int part, double in_db) {
    (void)part;
    double x = in_db + f->p[0];
    return x + comp_gain(x, f->p[1], f->p[2], f->p[5]) + f->p[6];
}

const kc_type kc_compressor_type = {"compressor", 7, comp_params, comp_defaults, sizeof(dyn_state), 0, dyn_reset,
                                    comp_process, 0, 0, 0, comp_response};

/* -- expander (downward): pre gain, threshold, ratio, attack, release, knee --------------------- */
static const char *const exp_params[] = {"gain", "thr", "ratio", "at", "rt", "knee"};
static const double exp_defaults[] = {0, -36, 2, 20, 100, 6};

static double exp_gain(double in_db, double thr, double ratio, double knee) {
    double under = thr - in_db, slope = kc_clamp(ratio, 1.0, 100.0) - 1.0, g;
    if (knee > 0.0 && fabs(under) < knee / 2)
        g = -slope * (under + knee / 2) * (under + knee / 2) / (2 * knee);
    else
        g = under > 0.0 ? -slope * under : 0.0;
    return g < -90.0 ? -90.0 : g;
}

static void exp_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    dyn_state *s = f->state;
    double pre = kc_db_lin(f->p[0]);
    double ka = pole(f->p[3], f->sr), kr = pole(f->p[4], f->sr), keep = pole(8.0, f->sr);
    double loud = 0, made = 0, down = 0;
    (void)pos;
    if (f->fresh)
        s->pre = pre;
    double dpre = (pre - s->pre) / n;
    for (int i = 0; i < n; i++) {
        s->pre += dpre;
        double level = detect(s, side ? side : in, i, side ? 1.0 : s->pre, keep);
        double want = exp_gain(kc_lin_db(level), f->p[1], f->p[2], f->p[5]);
        double k = want > s->gain_db ? ka : kr;     /* the attack is the way back up */
        s->gain_db = kc_flush(want + (s->gain_db - want) * k);
        double g = s->pre * kc_db_lin(s->gain_db);
        float l = (float)(in[2 * i] * g), r = (float)(in[2 * i + 1] * g);
        out[2 * i] = l;
        out[2 * i + 1] = r;
        if (level > loud) loud = level;
        if (fabsf(l) > made) made = fabsf(l);
        if (fabsf(r) > made) made = fabsf(r);
        if (-s->gain_db > down) down = -s->gain_db;
    }
    s->pre = pre;
    note(f, loud, made, down);
}

static double exp_response(const kc_fx *f, int part, double in_db) {
    (void)part;
    double x = in_db + f->p[0];
    return x + exp_gain(x, f->p[1], f->p[2], f->p[5]);
}

const kc_type kc_expander_type = {"expander", 6, exp_params, exp_defaults, sizeof(dyn_state), 0, dyn_reset, exp_process,
                                  0, 0, 0, exp_response};

/* -- gate: pre gain, threshold, how far it closes, attack, hold, release ------------------------ */
static const char *const gate_params[] = {"gain", "thr", "red", "at", "hold", "rt"};
static const double gate_defaults[] = {0, -40, 24, 10, 20, 100};

static void gate_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    dyn_state *s = f->state;
    double pre = kc_db_lin(f->p[0]), closed = -kc_clamp(f->p[2], 0.0, 90.0);
    double ka = pole(f->p[3], f->sr), kr = pole(f->p[5], f->sr), keep = pole(8.0, f->sr);
    double open_at = kc_db_lin(f->p[1]), close_at = kc_db_lin(f->p[1] - 3.0);     /* (no fluttering at the threshold) */
    double loud = 0, made = 0, down = 0;
    long hold = (long)(kc_clamp(f->p[4], 0.0, 5000.0) * 0.001 * f->sr);
    (void)pos;
    if (f->fresh) {
        s->pre = pre;
        s->gain_db = closed;
    }
    double dpre = (pre - s->pre) / n;
    for (int i = 0; i < n; i++) {
        s->pre += dpre;
        double level = detect(s, side ? side : in, i, side ? 1.0 : s->pre, keep);
        if (level >= (s->open ? close_at : open_at)) {
            s->open = 1;
            s->hold = hold;
        } else if (s->hold > 0) {
            s->hold--;
        } else {
            s->open = 0;
        }
        double want = s->open ? 0.0 : closed;
        double k = want > s->gain_db ? ka : kr;
        s->gain_db = kc_flush(want + (s->gain_db - want) * k);
        double g = s->pre * kc_db_lin(s->gain_db);
        float l = (float)(in[2 * i] * g), r = (float)(in[2 * i + 1] * g);
        out[2 * i] = l;
        out[2 * i + 1] = r;
        if (level > loud) loud = level;
        if (fabsf(l) > made) made = fabsf(l);
        if (fabsf(r) > made) made = fabsf(r);
        if (-s->gain_db > down) down = -s->gain_db;
    }
    s->pre = pre;
    note(f, loud, made, down);
}

static double gate_response(const kc_fx *f, int part, double in_db) {
    (void)part;
    double x = in_db + f->p[0];
    return x >= f->p[1] ? x : x - kc_clamp(f->p[2], 0.0, 90.0);
}

const kc_type kc_gate_type = {"gate", 6, gate_params, gate_defaults, sizeof(dyn_state), 0, dyn_reset, gate_process,
                              0, 0, 0, gate_response};

/* -- limiter: pre gain, ceiling, look-ahead, attack, release, long release (and its times) ------
 * Nothing passes the ceiling. The gain each sample needs is held back over the look-ahead
 * (a sliding minimum), let go at the release, then smoothed over the attack: by the time a
 * peak comes out of the delay the gain is all the way down for it. */
#define LIM_MAX 4096
typedef struct {
    float delay[LIM_MAX][2];
    double box[LIM_MAX];            /* the gains being averaged */
    double need[LIM_MAX];           /* sliding minimum: a queue of rising values ... */
    int64_t at[LIM_MAX];            /* ... and when each came in */
    int head, count;
    int64_t t;
    int len, attack;                /* the look-ahead and the averaging, in samples */
    double sum, rel, slow, pre, ceil;
} lim_state;

static const char *const lim_params[] = {"gain", "ceil", "lk", "at", "rt", "alr", "alr_at", "alr_rt"};
static const double lim_defaults[] = {0, -1, 5, 5, 50, 0, 5, 200};

static int lim_len(const kc_fx *f) {
    return (int)kc_clamp(floor(f->p[2] * 0.001 * f->sr + 0.5), 1, LIM_MAX);
}

static void lim_clear(lim_state *s, int len, int attack) {
    memset(s, 0, sizeof *s);
    s->len = len;
    s->attack = attack;
    for (int i = 0; i < attack; i++)
        s->box[i] = 1.0;
    s->sum = attack;
    s->rel = s->slow = 1.0;
}

static void lim_reset(kc_fx *f) { memset(f->state, 0, sizeof(lim_state)); }

static void lim_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    lim_state *s = f->state;
    int len = lim_len(f);
    int attack = (int)kc_clamp(floor(f->p[3] * 0.001 * f->sr + 0.5), 1, len);
    double pre = kc_db_lin(f->p[0]), top = kc_db_lin(f->p[1]);
    double kr = pole(f->p[4], f->sr), sa = pole(f->p[6], f->sr), sr_ = pole(f->p[7], f->sr);
    int alr = f->p[5] > 0.5;
    double loud = 0, made = 0, down = 0;
    (void)side; (void)pos;
    if (len != s->len || attack != s->attack)
        lim_clear(s, len, attack);
    if (f->fresh) {
        s->pre = pre;
        s->ceil = top;
    }
    double dpre = (pre - s->pre) / n;
    s->ceil = top;
    for (int i = 0; i < n; i++) {
        s->pre += dpre;
        float l = (float)(in[2 * i] * s->pre), r = (float)(in[2 * i + 1] * s->pre);
        double peak = fabsf(l) > fabsf(r) ? fabsf(l) : fabsf(r);
        double need = peak > top ? top / peak : 1.0;
        /* the smallest need of the last len samples */
        while (s->count && s->need[(s->head + s->count - 1) % LIM_MAX] >= need)
            s->count--;
        s->need[(s->head + s->count) % LIM_MAX] = need;
        s->at[(s->head + s->count) % LIM_MAX] = s->t;
        s->count++;
        if (s->at[s->head] <= s->t - len) {
            s->head = (s->head + 1) % LIM_MAX;
            s->count--;
        }
        double least = s->need[s->head];
        s->rel = least < s->rel ? least : least + (s->rel - least) * kr;
        double g = s->rel;
        if (alr) {                  /* 長釋放: a slower gain follows, and the lower of the two counts */
            s->slow = s->rel + (s->slow - s->rel) * (s->rel < s->slow ? sa : sr_);
            if (s->slow < g)
                g = s->slow;
        }
        int k = (int)(s->t % attack);
        s->sum += g - s->box[k];
        s->box[k] = g;
        g = s->sum / attack;
        int w = (int)(s->t % len);
        s->delay[w][0] = l;
        s->delay[w][1] = r;
        int rd = (int)((s->t + 1) % len);           /* len - 1 samples ago */
        float a = (float)(s->delay[rd][0] * g), b = (float)(s->delay[rd][1] * g);
        if (a > top) a = (float)top; else if (a < -top) a = (float)-top;     /* (rounding) */
        if (b > top) b = (float)top; else if (b < -top) b = (float)-top;
        out[2 * i] = a;
        out[2 * i + 1] = b;
        s->t++;
        if (peak > loud) loud = peak;
        if (fabsf(a) > made) made = fabsf(a);
        if (fabsf(b) > made) made = fabsf(b);
        double d = -kc_lin_db(g);
        if (d > down) down = d;
    }
    s->pre = pre;
    note(f, loud, made, down);
}

static int lim_latency(const kc_fx *f) { return lim_len(f) - 1; }
static double lim_tail(const kc_fx *f) { return lim_len(f) / f->sr; }

static double lim_response(const kc_fx *f, int part, double in_db) {
    (void)part;
    double x = in_db + f->p[0];
    return x > f->p[1] ? f->p[1] : x;
}

const kc_type kc_limiter_type = {"limiter", 8, lim_params, lim_defaults, sizeof(lim_state), 0, lim_reset, lim_process,
                                 lim_latency, lim_tail, 0, lim_response};

/* -- hard clip ---------------------------------------------------------------------------------- */
static const char *const clip_params[] = {"ceil"};
static const double clip_defaults[] = {-1};

static void clip_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    dyn_state *s = f->state;
    double top = kc_db_lin(f->p[0]), loud = 0, made = 0;
    (void)side; (void)pos;
    if (f->fresh)
        s->post = top;
    double d = (top - s->post) / n;
    for (int i = 0; i < n; i++) {
        s->post += d;
        for (int c = 0; c < 2; c++) {
            double v = in[2 * i + c];
            if (fabs(v) > loud) loud = fabs(v);
            v = kc_clamp(v, -s->post, s->post);
            if (fabs(v) > made) made = fabs(v);
            out[2 * i + c] = (float)v;
        }
    }
    s->post = top;
    note(f, loud, made, loud > top ? kc_lin_db(loud) - f->p[0] : 0.0);
}

static double clip_response(const kc_fx *f, int part, double in_db) {
    (void)part;
    return in_db > f->p[0] ? f->p[0] : in_db;
}

const kc_type kc_clip_type = {"clip", 1, clip_params, clip_defaults, sizeof(dyn_state), 0, dyn_reset, clip_process,
                              0, 0, 0, clip_response};

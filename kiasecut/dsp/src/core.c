/* The effects there are, and their instances. */
#include "kcdsp.h"

static const kc_type *const types[] = {&kc_gain_type, &kc_highpass_type, &kc_lowpass_type, &kc_eq_type, &kc_filter_type,
                                      &kc_analyzer_type, &kc_compressor_type, &kc_expander_type, &kc_gate_type,
                                      &kc_limiter_type, &kc_clip_type, &kc_reverb_type, &kc_delay_type, &kc_width_type,
                                      &kc_balance_type, &kc_swap_type, &kc_invert_type, &kc_mono_type};
#define NTYPES ((int)(sizeof types / sizeof types[0]))

KC_API int kc_abi(void) { return KC_ABI; }
KC_API int kc_type_count(void) { return NTYPES; }
KC_API const char *kc_type_name(int t) { return t >= 0 && t < NTYPES ? types[t]->name : 0; }
KC_API int kc_param_count(int t) { return t >= 0 && t < NTYPES ? types[t]->nparams : 0; }
KC_API const char *kc_param_name(int t, int i) { return i >= 0 && i < kc_param_count(t) ? types[t]->params[i] : 0; }
KC_API double kc_param_default(int t, int i) { return i >= 0 && i < kc_param_count(t) ? types[t]->defaults[i] : 0.0; }

KC_API void kc_reset(kc_fx *f) {
    if (f->type->reset)
        f->type->reset(f);
    memset(f->meters, 0, sizeof f->meters);
    f->fresh = 1;
}

KC_API void kc_free(kc_fx *f) {
    if (!f)
        return;
    if (f->type->destroy && f->state)
        f->type->destroy(f);
    free(f->state);
    free(f);
}

KC_API kc_fx *kc_new(int t, double sr) {
    if (t < 0 || t >= NTYPES || sr < 8000.0)
        return 0;
    kc_fx *f = calloc(1, sizeof *f);
    if (!f)
        return 0;
    f->type = types[t];
    f->sr = sr;
    for (int i = 0; i < f->type->nparams; i++)
        f->p[i] = f->type->defaults[i];
    f->state = calloc(1, f->type->state_size ? f->type->state_size : 1);
    if (!f->state || (f->type->init && !f->type->init(f))) {
        kc_free(f);
        return 0;
    }
    kc_reset(f);
    return f;
}

KC_API void kc_set(kc_fx *f, int i, double v) {
    if (i >= 0 && i < f->type->nparams && isfinite(v))
        f->p[i] = v;
}

KC_API void kc_process(kc_fx *f, const float *in, const float *side, float *out, int n, int64_t pos) {
    while (n > 0) {
        int m = n < KC_MAXBLOCK ? n : KC_MAXBLOCK;
        f->type->process(f, in, side, out, m, pos);
        f->fresh = 0;
        in += 2 * m;
        out += 2 * m;
        if (side)
            side += 2 * m;
        pos += m;
        n -= m;
    }
}

KC_API int kc_latency(const kc_fx *f) { return f->type->latency ? f->type->latency(f) : 0; }
KC_API double kc_tail(const kc_fx *f) { return f->type->tail ? f->type->tail(f) : 0.0; }

KC_API void kc_response(const kc_fx *f, int part, const double *hz, double *db, int n) {
    for (int i = 0; i < n; i++)
        db[i] = f->type->response ? f->type->response(f, part, hz[i]) : 0.0;
}

KC_API void kc_meters(const kc_fx *f, float *out, int n) {
    for (int i = 0; i < n; i++)
        out[i] = i < KC_METERS ? f->meters[i] : 0.0f;
}

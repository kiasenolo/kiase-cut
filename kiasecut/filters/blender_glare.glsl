// @filter [Blender] Glare
// @category Blender
// @description Blender 合成器的 Glare：亮部的光暈、鬼影、光芒、霧光、星芒、光束（在線性光裡運算）
// @output image "圖像"
// @output glare "光"
// @output highlights "亮部"
// @passes 128
// @levels 0f 0 1 2 3 4 5 6 7 8 9 10 11 10 9 8 7 6 5 4 3 2 1 0 0 0 0 0 0 0f 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 quality
// @extras - - - - - - - - - - - - - 11 10 9 8 7 6 5 4 3 2 1 0 - 0 - 25 0 0 - - - - - 0 - - - - 35 0 - - - - 41 0 - - - - 47 0 - - - - 53 0 - - - - 59 0 - - - - 65 0 - - - - 71 0 - - - - 77 0 - - - - 83 0 - - - - 89 0 - - - - 95 0 - - - - 101 0 - - - - 107 0 - - - - 113 0 - - - - 119 0 -
// @shared
// @alone highlights
// @skip 1-23 type != Bloom
// @skip 24-28 type != Ghosts
// @skip 29 type != Sun Beams
// @skip 30-125 type != Streaks
// @skip 32-125/6 iterations == 2
// @skip 33-125/6 iterations == 2|3
// @skip 34-125/6 iterations == 2|3|4
// @skip 36-41 streaks == 1
// @skip 42-47 streaks == 1|2
// @skip 48-53 streaks == 1|2|3
// @skip 54-59 streaks == 1|2|3|4
// @skip 60-65 streaks == 1|2|3|4|5
// @skip 66-71 streaks == 1|2|3|4|5|6
// @skip 72-77 streaks == 1|2|3|4|5|6|7
// @skip 78-83 streaks == 1|2|3|4|5|6|7|8
// @skip 84-89 streaks == 1|2|3|4|5|6|7|8|9
// @skip 90-95 streaks == 1|2|3|4|5|6|7|8|9|10
// @skip 96-101 streaks == 1|2|3|4|5|6|7|8|9|10|11
// @skip 102-107 streaks == 1|2|3|4|5|6|7|8|9|10|11|12
// @skip 108-113 streaks == 1|2|3|4|5|6|7|8|9|10|11|12|13
// @skip 114-119 streaks == 1|2|3|4|5|6|7|8|9|10|11|12|13|14
// @skip 120-125 streaks == 1|2|3|4|5|6|7|8|9|10|11|12|13|14|15
// @slot streak_a 30-125/6 32-125/6 34-125/6
// @slot streak_b 31-125/6 33-125/6
// @slot streaks_p 35-125/12
// @slot streaks_q 41-125/12
// @precision float
// @bake type
// @param type menu Bloom "Bloom|Ghosts|Streaks|Fog Glow|Simple Star|Sun Beams" "類型"
// @param quality menu 中 "高|中|低" "品質"
// @panel 亮部
// @param threshold float 0.7 0 1 "亮度門檻"
// @param smoothness float 0.1 0 1 "門檻柔邊"
// @param clamp_on bool false "限制亮度"
// @param maximum float 1 0 1 "最大亮度"
// @panel 調整
// @param strength float 1 0 4 "強度"
// @param saturation float 1 0 1 "飽和度"
// @param tint color #ffffff "光的顏色"
// @panel 光芒
// @param size float 0.5 0 1 "大小"
// @param streaks int 4 1 16 "光芒數"
// @param streak_angle float 0 -180 180 "光芒角度"
// @param iterations int 3 2 5 "光芒長度"
// @param fade float 0.9 0.75 1 "光芒衰減"
// @param color_modulation float 0.25 0 1 "色彩調變"
// @param diagonal bool true "斜向星芒"
// @param sun_position vec2 0.5,0.5 0 1 "光源位置"
// @param full bool false "計算全圖"
// @enable maximum clamp_on
// @enable size type == Bloom|Fog Glow|Sun Beams
// @enable streaks type == Streaks
// @enable streak_angle type == Streaks
// @enable iterations type == Streaks
// @enable fade type == Streaks
// @enable color_modulation type == Ghosts|Streaks
// @enable diagonal type == Simple Star
// @enable sun_position type == Sun Beams

// Source: Blender's Glare compositor node, rewritten by hand for KiaseCut (exported first with
// tools/converters/compositor_to_hyprshade.py).
// Blender: https://github.com/blender/blender
//   source/blender/nodes/composite/nodes/node_composite_glare.cc
//   source/blender/compositor/shaders/compositor_glare_*.glsl
// SPDX-FileCopyrightText: Blender Authors (original); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later
// (Blender's code is GPL-2.0-or-later.)

// (Streaks uses passes 30 - 125: see streak_pass. Ghosts uses passes 24 - 28: see ghost_blur. Sun Beams uses pass 29 - the glare's size - for the sums of the highlights along short runs of steps towards the sun, which
// its gather reads instead of every step: see sun_runs. Bloom's chain is left out for it, as for the other types.)
// Pass 0 keeps the highlights (what glows, as Blender computes it). Bloom is Blender's own chain, one
// pass per step (@levels shrinks them): pass 1 the highlights at the glare's size, passes 2 - 12 the
// downsamples (13 taps, the first Karis-weighted), passes 13 - 23 the upsamples (3 x 3 tent, each level
// added to the one before it); every other type is gathered in the last pass from pass 0 (@extras), each
// sample one read of it. 品質 中 / 低 work on a picture 2 / 4 times smaller, as Blender's do.

vec3 srgb_to_lin(vec3 c) { return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(vec3(0.04045), c)); }
vec3 lin_to_srgb(vec3 c) { c = clamp(c, 0.0, 1.0); return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(vec3(0.0031308), c)); }
float hash31(vec3 p) { p = fract(p * 0.1031); p += dot(p, p.zyx + 31.32); return fract((p.x + p.y) * p.z); }

vec4 linear(vec4 s) { vec4 c = unpremultiply(s); return vec4(srgb_to_lin(c.rgb) * c.a, c.a); }

// the highlights: the brightness (HSV value) smoothly clamped to [threshold, maximum], made
// relative to the threshold
float smooth_min(float a, float b, float s) {
    if (s <= 0.0) return min(a, b);
    float h = max(s - abs(a - b), 0.0) / s;
    return min(a, b) - h * h * s * 0.25;
}
vec3 highlights(vec3 c) {
    float thr = max(threshold, 0.0), sm = max(smoothness, 0.0);
    float mx = clamp_on ? thr + max(maximum, 0.0) : 1.0e30;
    float v = max(c.r, max(c.g, c.b));
    float range = abs(mx - thr);
    float b = -smooth_min(-thr, -v, min(sm, min(thr, range)));
    b = smooth_min(mx, b, min(sm, min(abs(mx), range)));
    return v > 0.0 ? c * ((b - thr) / v) : vec3(0.0);
}

// c read at p: none outside the frame
vec4 inside_or_none(vec4 c, vec2 p) { return p.x < 0.0 || p.y < 0.0 || p.x > 1.0 || p.y > 1.0 ? vec4(0.0) : c; }

// pass 0's highlights at p (kept as 16-bit floats, linear); none outside
vec3 H(vec2 p) {
    if (p.x < 0.0 || p.y < 0.0 || p.x > 1.0 || p.y > 1.0) return vec3(0.0);
    return extra(p).rgb;
}

vec3 rgb2hsv(vec3 c) {
    vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
    vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
    float d = q.x - min(q.w, q.y);
    return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + 1e-10)), d / (q.x + 1e-10), q.x);
}
vec3 hsv2rgb(vec3 c) {
    vec3 p = abs(fract(c.xxx + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
    return c.z * mix(vec3(1.0), clamp(p - 1.0, 0.0, 1.0), c.y);
}

// Fog Glow: Blender's point spread function of the angle th (degrees) ...
float fog_psf(float th) {
    float f0 = 2.61e6 * exp(-(th / 0.02) * (th / 0.02));
    float f1 = 20.91 / pow(th + 0.02, 3.0);
    float f2 = 72.37 / ((th + 0.02) * (th + 0.02));
    return 0.384 * f0 + 0.478 * f1 + 0.138 * f2;
}
// ... and its integral over the ring a <= r <= b (pixels; dpp: degrees per pixel)
float fog_psf_ring(float a, float b, float dpp) {
    float s = 0.02 / dpp;
    float i0 = 3.14159265 * 2.61e6 * s * s * (exp(-(a / s) * (a / s)) - exp(-(b / s) * (b / s)));
    float ua = a * dpp + 0.02, ub = b * dpp + 0.02, k = 6.2831853 / (dpp * dpp);
    float i1 = k * 20.91 * ((1.0 / ua - 0.01 / (ua * ua)) - (1.0 / ub - 0.01 / (ub * ub)));
    float i2 = k * 72.37 * (log(ub / ua) + 0.02 / ub - 0.02 / ua);
    return 0.384 * i0 + 0.478 * i1 + 0.138 * i2;
}

vec2 r2(int i, float a, float b) { return fract(vec2(0.7548776662, 0.5698402910) * float(i + 1) + vec2(a, b)); }

// Blender's Bloom: a chain of floor(log2(smaller side of the glare picture * size)) pictures, each half the one before
int bloom_length() {
    float q = exp2(float(quality));
    vec2 g = floor(resolution / q);
    return min(int(log2(max(1.0, min(g.x, g.y) * clamp(size, 0.0, 1.0)) + 1e-5)), 12);
}
float brightest(vec4 c) { return max(max(c.r, c.g), max(c.b, c.a)); }    // (all four, alpha 1 included, as Blender's reduce_max)
vec4 karis(vec4 a, vec4 b, vec4 c, vec4 d) {
    float wa = 1.0 / (brightest(a) + 1.0), wb = 1.0 / (brightest(b) + 1.0);
    float wc = 1.0 / (brightest(c) + 1.0), wd = 1.0 / (brightest(d) + 1.0);
    return (a * wa + b * wb + c * wc + d * wd) / (wa + wb + wc + wd);
}
// pass k + 1 (k >= 1): picture k of the chain from picture k - 1 (the pass before), 13 bilinear taps
vec4 bloom_down(vec2 uv, int k) {
    if (k >= bloom_length()) return vec4(0.0);
    vec2 ps = 1.0 / src_px;
    vec4 c  = src(uv);
    vec4 ul = src(uv + ps * vec2(-1.0,  1.0)), ur = src(uv + ps * vec2( 1.0,  1.0));
    vec4 ll = src(uv + ps * vec2(-1.0, -1.0)), lr = src(uv + ps * vec2( 1.0, -1.0));
    vec4 lf = src(uv + ps * vec2(-2.0,  0.0)), rf = src(uv + ps * vec2( 2.0,  0.0));
    vec4 uf = src(uv + ps * vec2( 0.0,  2.0)), df = src(uv + ps * vec2( 0.0, -2.0));
    vec4 ulf = src(uv + ps * vec2(-2.0,  2.0)), urf = src(uv + ps * vec2( 2.0,  2.0));
    vec4 llf = src(uv + ps * vec2(-2.0, -2.0)), lrf = src(uv + ps * vec2( 2.0, -2.0));
    if (k == 1)
        return vec4((4.0 / 8.0) * karis(ul, ur, lr, ll).rgb + (1.0 / 8.0) * (karis(ulf, uf, c, lf).rgb + karis(uf, urf, rf, c).rgb
                  + karis(c, rf, lrf, df).rgb + karis(lf, c, df, llf).rgb), 1.0);
    return vec4((4.0 / 32.0) * c.rgb + (4.0 / 32.0) * (ul.rgb + ur.rgb + ll.rgb + lr.rgb)
              + (2.0 / 32.0) * (lf.rgb + rf.rgb + uf.rgb + df.rgb) + (1.0 / 32.0) * (ulf.rgb + urf.rgb + llf.rgb + lrf.rgb), 1.0);
}
// passes 13 - 23 (l = 10 .. 0): picture l of the chain plus the one above it (the pass before) spread by a 3 x 3 tent
vec4 bloom_up(vec2 uv, int l) {
    int len = bloom_length();
    if (l >= len) return vec4(0.0);
    vec4 base = extra(uv);
    if (l == len - 1) return vec4(base.rgb, 1.0);
    vec2 ps = 1.0 / pass_px;
    vec3 up = (4.0 / 16.0) * src(uv).rgb
            + (2.0 / 16.0) * (src(uv + ps * vec2(-1.0, 0.0)).rgb + src(uv + ps * vec2(0.0, 1.0)).rgb
                            + src(uv + ps * vec2(1.0, 0.0)).rgb + src(uv + ps * vec2(0.0, -1.0)).rgb)
            + (1.0 / 16.0) * (src(uv + ps * vec2(-1.0, -1.0)).rgb + src(uv + ps * vec2(-1.0, 1.0)).rgb
                            + src(uv + ps * vec2(1.0, -1.0)).rgb + src(uv + ps * vec2(1.0, 1.0)).rgb);
    return vec4(base.rgb + up, 1.0);
}
vec3 bloom(vec2 uv) { return bloom_length() < 2 ? extra(uv).rgb : src(uv).rgb; }

vec3 ghosts_sampled(vec2 uv, vec2 R, float q) {
    vec2 y = uv - 0.5;
    float D = 2.0 * length(y);
    float cg = 1.0 - clamp(color_modulation, 0.0, 1.0);
    // Blender's ghosts: 4 copies of the blurred highlights, then 4 copies of that sum (scale, strength, colour)
    float ts[20] = float[20](1.3125, -0.87033, 0.9625, -1.257143, 0.803906, -0.533077, 0.589531, -0.77, -2.97, 1.969432,
                             -2.178, 2.844735, 0.344531, -0.228462, 0.252656, -0.33, -14.85, 9.847159, -10.89, 14.223673);
    float s1[20] = float[20](0.0, 0.0, 0.0, 0.0, 0.6125, 0.6125, 0.6125, 0.6125, 2.262857, 2.262857,
                             2.262857, 2.262857, 0.2625, 0.2625, 0.2625, 0.2625, 11.314286, 11.314286, 11.314286, 11.314286);
    vec3 tm[20] = vec3[20](vec3(0, 0, 0), vec3(0, 1, 1), vec3(1, 1, 0), vec3(1, 0, 1), vec3(0, 0, 0), vec3(0, 1, 1),
                           vec3(1, 1, 0), vec3(1, 0, 1), vec3(0, 1, 1), vec3(0, 2, 2), vec3(1, 2, 1), vec3(1, 1, 2),
                           vec3(1, 1, 0), vec3(1, 2, 1), vec3(2, 2, 0), vec3(2, 1, 1), vec3(1, 0, 1), vec3(1, 1, 2),
                           vec3(2, 1, 1), vec3(2, 0, 2));
    float rot = hash31(vec3(gl_FragCoord.xy, 8.0)), jr = hash31(vec3(gl_FragCoord.xy, 9.0));
    int ns = quality == 0 ? 8 : quality == 1 ? 6 : 4;
    vec3 g = vec3(0.0);
    for (int t = 0; t < 20; t++) {
        float ta = t < 4 ? max(0.0, 1.0 - D * abs(ts[t])) * 0.25
                         : max(0.0, 1.0 - D * s1[t]) * max(0.0, 1.0 - D * abs(ts[t])) * 0.0625;
        if (ta <= 0.0) continue;
        vec2 z = y * ts[t];
        float dz = 2.0 * length(z);
        float wsm = max(0.0, 1.0 - dz * 2.13), wbg = max(0.0, 1.0 - dz * 0.97);
        if (wsm <= 0.0 && wbg <= 0.0) continue;
        vec2 cs = 0.5 + z * 2.13, cb = 0.5 - z * 0.97;
        vec3 acc = vec3(0.0);
        for (int i = 0; i < ns; i++) {          // (each term turned differently: their noise averages out)
            vec2 rq = r2(i, jr, rot + 0.618034 * float(t));
            float rr = sqrt(-2.0 * log(max(1.0 - rq.x, 1e-4)));
            vec2 o = rr * vec2(cos(6.2831853 * rq.y), sin(6.2831853 * rq.y)) * (16.0 / 3.0) / R;     // (the same width in canvas px at every quality)
            if (wsm > 0.0) acc += wsm * H(cs + o);
            if (wbg > 0.0) acc += wbg * H(cb + 2.0 * o);
        }
        g += ta * pow(vec3(max(cg, 1e-6)), tm[t]) * acc / float(ns);    // (pow(0, 0) is undefined)
    }
    return g;
}

// how many of a streak's iterations are read every few pixels (the skipped ones folded into a weight)
int streak_skip() {
    float fd = clamp(fade, 0.75, 1.0);
    int N = clamp(iterations, 2, 5);
    int ns = clamp(streaks, 1, 16);
    float total = exp2(2.0 * float(N));
    float nmax = fd < 1.0 ? min(total, ceil(log(1e-3) / log(fd))) : total;
    float per = float(max(min(1024, 2048 / ns), 4));
    int m = 0;
    while (m < N && nmax / exp2(2.0 * float(m)) > per) m++;
    return m;
}

vec3 streak_lines(vec2 uv, vec2 R, float q) {
    float fd = clamp(fade, 0.75, 1.0);
    float cm = clamp(color_modulation, 0.0, 1.0);
    int N = clamp(iterations, 2, 5);
    int ns = clamp(streaks, 1, 16);
    float total = exp2(2.0 * float(N));
    float nmax = fd < 1.0 ? min(total, ceil(log(1e-3) / log(fd))) : total;
    // Blender's streak after N iterations, read every st-th pixel (the skipped ones folded into wlow)
    int m = streak_skip();
    vec3 wlow = vec3(1.0);
    for (int k = 0; k < m; k++) {
        float c = 1.0 - pow(cm, float(k + 1));
        float f1 = pow(fd, exp2(2.0 * float(k)));
        wlow *= vec3(1.0) + f1 * vec3(1.0, c, c) + f1 * f1 * vec3(c, c, 1.0) + f1 * f1 * f1 * vec3(c, 1.0, c);
    }
    float st = exp2(2.0 * float(m));
    float jit = m > 0 ? hash31(vec3(gl_FragCoord.xy, 7.0)) * st : 0.0;
    int nt = int(ceil(nmax / st));
    vec3 acc = vec3(0.0);
    for (int si = 0; si < ns; si++) {
        float an = radians(streak_angle) + float(si) / float(ns) * 6.2831853;
        vec2 d = vec2(cos(an), -sin(an)) * q / R;            // (counter-clockwise on the picture, as in Blender)
        for (int t = 0; t < nt; t++) {
            int n = t << (2 * m);
            vec3 w = wlow * pow(fd, float(n));
            for (int k = m; k < N; k++) {
                int j = (n >> (2 * k)) & 3;
                float c = 1.0 - pow(cm, float(k + 1));
                w *= j == 1 ? vec3(1.0, c, c) : j == 2 ? vec3(c, c, 1.0) : j == 3 ? vec3(c, 1.0, c) : vec3(1.0);
            }
            acc += w * H(uv + d * (float(n) + jit));
        }
    }
    return acc * exp2(-float(N)) / float(6 - N);               // shorter streaks are attenuated more
}

// Streaks by passes, as Blender's: every streak is the highlights filtered `iterations` times along its direction, each time
// with the picture and 3 copies of it 1, 2, 3 steps on (4^k glare pixels a step at iteration k) faded and tinted, halved;
// the streaks are added up into one picture (passes 30 - 125: six for each of up to 16 streaks - 5 iterations, then the sum;
// two pictures taking turns for the iterations and two for the sums, @slot). Each pixel reads 4 per iteration instead of
// every step of streak_lines (4^iterations of them, read every few pixels when long), which is kept for a margin.
vec4 streak_in(vec2 p, int k) { return k == 0 ? vec4(H(p), 1.0) : inside_or_none(src(p), p); }
vec4 streak_pass(vec2 uv) {
    int s = (pass_index - 30) / 6, k = (pass_index - 30) - 6 * s;
    int N = clamp(iterations, 2, 5), ns = clamp(streaks, 1, 16);
    if (k == 5) {                                              // the sum: the streaks before it and this one
        vec3 before = s == 0 ? vec3(0.0) : extra(uv).rgb;
        if (s >= ns || ov_scale != vec2(1.0)) return vec4(before, 1.0);
        return vec4(before + src(uv).rgb / float(6 - N), 1.0);    // (shorter streaks are attenuated more)
    }
    if (ov_scale != vec2(1.0)) return vec4(0.0);
    if (k >= N) return streak_in(uv, k);                       // (iterations past the setting: left as it is)
    float q = quality == 0 ? 1.0 : quality == 1 ? 2.0 : 4.0;
    float an = radians(streak_angle) + float(s) / float(ns) * 6.2831853;
    vec2 d = vec2(cos(an), -sin(an)) * q / resolution * exp2(2.0 * float(k));    // (counter-clockwise on the picture, as in Blender)
    float b = exp2(2.0 * float(k)), fd = clamp(fade, 0.75, 1.0);
    float c = 1.0 - pow(clamp(color_modulation, 0.0, 1.0), float(k + 1));
    vec3 g = streak_in(uv, k).rgb
           + pow(fd, b) * vec3(1.0, c, c) * streak_in(uv + d, k).rgb
           + pow(fd, 2.0 * b) * vec3(c, c, 1.0) * streak_in(uv + 2.0 * d, k).rgb
           + pow(fd, 3.0 * b) * vec3(c, 1.0, c) * streak_in(uv + 3.0 * d, k).rgb;
    return vec4(0.5 * g, 1.0);
}
vec3 streaks_of(vec2 uv, vec2 R, float q) {
    return ov_scale != vec2(1.0) ? streak_lines(uv, R, q) : inside_or_none(src(uv), uv).rgb;
}

vec3 fog_glow(vec2 uv, vec2 R, float q) {
    vec2 Rh = R / q;                                           // in glare pixels (q canvas px each)
    float K = max(Rh.x, Rh.y);
    float dpp = mix(180.0, 10.0, pow(clamp(size, 0.0, 1.0), 1.0 / 3.0)) / K;
    vec3 acc = vec3(0.0);
    float wn = 0.0;
    for (int dy = -2; dy <= 2; dy++) {                         // near: the 5 x 5 pixels around
        for (int dx = -2; dx <= 2; dx++) {
            vec2 dd = vec2(float(dx), float(dy));
            float w = fog_psf(length(dd) * dpp);
            wn += w;
            acc += w * H(uv + dd / Rh);
        }
    }
    float r0 = 2.5, r1 = max(length(Rh), 3.5);                 // far: sampled on a log scale (nothing is lit beyond the image)
    float lr = log(r1 / r0);
    float rot = hash31(vec3(gl_FragCoord.xy, 10.0)), jr = hash31(vec3(gl_FragCoord.xy, 11.0));
    int ns = quality == 0 ? 48 : quality == 1 ? 32 : 20;
    for (int i = 0; i < ns; i++) {
        vec2 rq = r2(i, jr, rot);
        float r = r0 * exp(lr * rq.x);
        vec2 p = uv + r * vec2(cos(6.2831853 * rq.y), sin(6.2831853 * rq.y)) / Rh;
        acc += fog_psf(r * dpp) * 6.2831853 * r * r * lr / float(ns) * H(p);
    }
    vec2 S = Rh + K;                                           // the padded domain, as a disc of the same area
    return acc / (wn + fog_psf_ring(r0, sqrt(S.x * S.y / 3.14159265), dpp));
}

vec3 simple_star(vec2 uv, vec2 R, float q) {
    vec2 d1 = (diagonal ? vec2(1.0, 1.0) : vec2(1.0, 0.0)) * q / R;
    vec2 d2 = (diagonal ? vec2(-1.0, 1.0) : vec2(0.0, 1.0)) * q / R;
    float wk[25] = float[25](0.135551, 0.106207, 0.097758, 0.066360, 0.052346, 0.033622, 0.025248, 0.015891, 0.011704,
                             0.007305, 0.005336, 0.003319, 0.002415, 0.001500, 0.001090, 0.000676, 0.000491, 0.000305,
                             0.000221, 0.000137, 0.000099, 0.000062, 0.000045, 0.000028, 0.000020);
    vec3 g = 2.0 * wk[0] * H(uv);                              // the centre is in both lines
    for (int k = 1; k < 25; k++)
        g += wk[k] * (H(uv + d1 * float(k)) + H(uv - d1 * float(k)) + H(uv + d2 * float(k)) + H(uv - d2 * float(k)));
    return g;
}

// Ghosts by passes, as Blender's: the highlights blurred twice (a Gaussian of 16 / 3 canvas px for the small ghosts, 32 / 3
// for the big; passes 24 - 27, each one way), the 4 scaled copies of their sum made once (pass 28, ghost_acc), and the
// gather adds that and 4 scaled copies of it. Every term of ghosts_sampled, which reads the blur at random spots (~320 reads a
// pixel, then smoothed), comes out of these; under a margin that one is used still.
const float GHOST_SCALE[4] = float[4](1.3125, -0.87033, 0.9625, -1.257143);
const float GHOST_OUTER[4] = float[4](0.6125, -2.262857, 0.2625, -11.314286);
const vec3 GHOST_TINT[4] = vec3[4](vec3(0, 0, 0), vec3(0, 1, 1), vec3(1, 1, 0), vec3(1, 0, 1));

// passes 24 - 27: one way of a Gaussian blur of the highlights (24, 26: across, from pass 0; 25, 27: down, from the pass before)
vec4 ghost_blur(vec2 uv) {
    bool big = pass_index >= 26, across = pass_index == 24 || pass_index == 26;
    float sigma = (big ? 32.0 : 16.0) / 3.0 * pass_px.x / resolution.x;         // (this pass's px)
    int r = int(ceil(3.0 * sigma));
    vec2 step_ = (across ? vec2(1.0, 0.0) : vec2(0.0, 1.0)) / pass_px;
    // two neighbouring taps are one read between them, weighed as both (exact where the picture read has this pass's pixels:
    // the bilinear read is their weighted sum); a pair with a tap past the frame is read tap by tap (none there)
    bool pairs = (across ? extra_px : src_px) == pass_px;
    vec3 acc = vec3(0.0);
    float wsum = 0.0;
    for (int i = -r; i <= r; i += pairs ? 2 : 1) {
        float w1 = exp(-0.5 * float(i * i) / (sigma * sigma));
        float w2 = pairs && i < r ? exp(-0.5 * float((i + 1) * (i + 1)) / (sigma * sigma)) : 0.0;
        vec2 p1 = uv + step_ * float(i), p2 = uv + step_ * float(i + 1);
        bool in2 = p2.x >= 0.0 && p2.y >= 0.0 && p2.x <= 1.0 && p2.y <= 1.0;
        bool in1 = p1.x >= 0.0 && p1.y >= 0.0 && p1.x <= 1.0 && p1.y <= 1.0;
        if (w2 > 0.0 && in1 && in2) {
            vec2 p = uv + step_ * (float(i) + w2 / (w1 + w2));
            acc += (w1 + w2) * (across ? extra(p).rgb : src(p).rgb);
        } else {
            acc += w1 * (across ? H(p1) : inside_or_none(src(p1), p1).rgb);
            if (w2 > 0.0)
                acc += w2 * (across ? H(p2) : inside_or_none(src(p2), p2).rgb);
        }
        wsum += w1 + w2;
    }
    return vec4(acc / wsum, 1.0);
}
// a picture of the blurred highlights read at p, none outside the frame: the small ghosts' (extra) or the big ones' (src)
vec3 ghost_small(vec2 p) { return inside_or_none(extra(p), p).rgb; }
vec3 ghost_big(vec2 p) { return inside_or_none(src(p), p).rgb; }
vec3 ghost_base(vec2 p) {                                       // the small ghost and the big one, as Blender's base
    vec2 z = p - 0.5;
    float dz = 2.0 * length(z);
    float wsm = max(0.0, 1.0 - dz * 2.13), wbg = max(0.0, 1.0 - dz * 0.97);
    vec3 c = vec3(0.0);
    if (wsm > 0.0) c += wsm * ghost_small(0.5 + z * 2.13);
    if (wbg > 0.0) c += wbg * ghost_big(0.5 - z * 0.97);
    return c;
}
vec3 ghost_tint(int i) { return pow(vec3(max(1.0 - clamp(color_modulation, 0.0, 1.0), 1e-6)), GHOST_TINT[i]); }    // (pow(0, 0) is undefined)
// pass 28: the 4 scaled copies of the base
vec4 ghost_acc(vec2 uv) {
    vec2 y = uv - 0.5;
    float D = 2.0 * length(y);
    vec3 g = vec3(0.0);
    for (int i = 0; i < 4; i++) {
        float a = max(0.0, 1.0 - D * abs(GHOST_SCALE[i])) * 0.25;
        if (a > 0.0) g += a * ghost_tint(i) * ghost_base(0.5 + y * GHOST_SCALE[i]);
    }
    return vec4(g, 1.0);
}
// the gather: pass 28's picture and 4 scaled copies of it
vec3 ghosts(vec2 uv, vec2 R, float q) {
    if (ov_scale != vec2(1.0)) return ghosts_sampled(uv, R, q);
    vec2 y = uv - 0.5;
    float D = 2.0 * length(y);
    vec3 g = inside_or_none(src(uv), uv).rgb;
    for (int j = 0; j < 4; j++) {
        float a = max(0.0, 1.0 - D * abs(GHOST_OUTER[j])) * 0.25;
        vec2 p = 0.5 + y * GHOST_OUTER[j];
        if (a > 0.0) g += a * ghost_tint(j) * inside_or_none(src(p), p).rgb;
    }
    return g;
}

// Sun Beams. Every pixel adds up the highlights along the line from it towards the sun, one step per glare pixel (q canvas px;
// never finer than the gather's own pixels), step i of n weighed (1 - t)^2 at t = (i + 0.5) / n, as Blender's. A sun far
// away takes thousands of steps per pixel; but the pixels on one line to the sun read the same spots, so pass 24 adds up
// SUN_RUN steps from each of its pixels once (sun_runs), and the gather reads those sums: a run's weights are a polynomial
// in its steps, so the run's sum and its first moment give them (to 1 / n^2: the second moment taken as for an even run).
// Runs are read between the pixels of pass 24 (bilinear), which softens the beams across by about a glare pixel; the
// steps nearest the pixel, which weigh the most, are still read one by one.
const int SUN_RUN = 16;
const int SUN_NEAR = 32;                                       // steps read one by one before the runs
float sun_steps(float L, float step_px) { return clamp(ceil(L / step_px), 1.0, 2304.0); }

// pass 24: from this pixel towards the sun, the sum of SUN_RUN steps of the highlights (rgb) and (a) the first moment of
// their r + g + b about the run's middle
vec4 sun_runs(vec2 uv) {
    if (ov_scale != vec2(1.0)) return vec4(0.0);               // (under a margin the gather reads every step itself)
    vec2 G = vec2(textureSize(original_, 0));                  // (the gather's pixels: the picture's)
    float k = G.x / resolution.x;
    float q = quality == 0 ? 1.0 : quality == 1 ? 2.0 : 4.0;
    float step_px = max(1.0, q * k);
    vec2 P = uv * G;
    vec2 v = vec2(sun_position.x, 1.0 - sun_position.y) * G - P;
    vec2 dir = v / max(length(v), 1e-6);
    vec3 s = vec3(0.0);
    float m = 0.0;
    for (int j = 0; j < SUN_RUN; j++) {
        vec3 h = H((P + dir * (float(j) * step_px)) / G);
        s += h;
        m += (float(j) - 0.5 * float(SUN_RUN - 1)) * (h.r + h.g + h.b);
    }
    return vec4(s, m);
}

vec3 sun_beams(vec2 uv, vec2 R, float q) {
    float k = pass_px.x / R.x;                                 // this pass's px per canvas px
    vec2 P = uv * pass_px;
    vec2 v = vec2(sun_position.x, 1.0 - sun_position.y) * pass_px - P;     // (y up from the bottom, as Blender's: pictures are stored top row first)
    float dist = length(v);
    vec2 dir = v / max(dist, 1e-6);
    float L = min(max(size, 0.0) * length(pass_px), dist);
    float step_px = max(1.0, q * k);
    int steps = int(sun_steps(L, step_px));
    float n = float(steps);
    float wsum = (4.0 * n * n - 1.0) / (12.0 * n);             // (the weights' sum, worked out whole)
    float h = L / n;
    vec3 acc = vec3(0.0);
    int i = 0;
    if (ov_scale == vec2(1.0) && steps >= SUN_NEAR + 2 * SUN_RUN) {
        for (; i < SUN_NEAR; i++) {
            float t = (float(i) + 0.5) / n;
            acc += (1.0 - t) * (1.0 - t) * H((P + dir * t * L) / pass_px);
        }
        float half_ = 0.5 * float(SUN_RUN - 1);
        float even = float(SUN_RUN * SUN_RUN - 1) / 12.0;     // (the mean of (j - middle)^2 over a run)
        for (; i + SUN_RUN <= steps; i += SUN_RUN) {
            vec2 p = (P + dir * ((float(i) + 0.5) * h)) / pass_px;
            if (p.x < 0.0 || p.y < 0.0 || p.x > 1.0 || p.y > 1.0) {   // (past the frame, where the highlights are none: the line never comes back in)
                i = steps;
                break;
            }
            vec4 r = src(p);
            float a = 1.0 - (float(i) + half_ + 0.5) / n;      // (1 - t at the run's middle)
            float lum = r.r + r.g + r.b;
            acc += (a * a + even / (n * n)) * r.rgb - (2.0 * a / n) * (lum > 0.0 ? r.a / lum : 0.0) * r.rgb;
        }
    }
    for (; i < steps; i++) {
        float t = (float(i) + 0.5) / n;
        acc += (1.0 - t) * (1.0 - t) * H((P + dir * t * L) / pass_px);
    }
    return max(acc, vec3(0.0)) / max(wsum, 1e-6);
}

// the gathered light's grain (the types that read at random spots - ghosts, fog glow, sun beams, long
// streaks - leave some) is smoothed over a few pixels of this very picture: a small Gaussian
float grain_sigma() {
    if (type == 3) return 2.0;
    if (type == 1) return ov_scale != vec2(1.0) ? 1.6 : 0.0;       // (only the sampled ghosts: the passes' have none)
    if (type == 2 && streak_skip() > 0 && ov_scale != vec2(1.0)) return 1.1;     // (only the gather of streak_lines: under a margin)
    return 0.0;
}

// the highlights of the picture 品質 reduces (Blender's: 中 the 2 x 2 block's mean, 低 four taps over the 4 x 4 block, in linear light), at the reduced pixel whose centre is uv
vec3 reduced_highlights(vec2 uv) {
    vec3 c = linear(original(uv)).rgb;
    if (quality == 2) {
        vec2 o = 1.0 / resolution;
        c = 0.25 * (linear(original(uv + o * vec2(-1.0, -1.0))).rgb + linear(original(uv + o * vec2(1.0, -1.0))).rgb
                  + linear(original(uv + o * vec2(-1.0, 1.0))).rgb + linear(original(uv + o * vec2(1.0, 1.0))).rgb);
    }
    return max(highlights(c), vec3(0.0));
}
// the same, read at any uv by bilinear interpolation of the reduced picture (the Highlights output of 中 / 低)
vec3 reduced_highlights_at(vec2 uv) {
    vec2 g = floor(resolution / exp2(float(quality)));
    vec2 f = uv * g - 0.5;
    vec2 i0 = floor(f), fr = f - i0;
    vec3 a = reduced_highlights((clamp(i0, vec2(0.0), g - 1.0) + 0.5) / g);
    vec3 b = reduced_highlights((clamp(i0 + vec2(1.0, 0.0), vec2(0.0), g - 1.0) + 0.5) / g);
    vec3 c = reduced_highlights((clamp(i0 + vec2(0.0, 1.0), vec2(0.0), g - 1.0) + 0.5) / g);
    vec3 d = reduced_highlights((clamp(i0 + vec2(1.0), vec2(0.0), g - 1.0) + 0.5) / g);
    return mix(mix(a, b, fr.x), mix(c, d, fr.x), fr.y);
}

vec4 effect(vec2 uv) {
    if (pass_index == 0)
        return vec4(reduced_highlights(uv), 1.0);
    if (pass_index >= 24 && pass_index <= 27) return ghost_blur(uv);
    if (pass_index == 28) return ghost_acc(uv);
    if (pass_index == 29) return sun_runs(uv);
    if (pass_index >= 30 && pass_index < 126) return streak_pass(uv);
    if (pass_index < 24) {                                     // (Bloom's chain; the other types leave it empty)
        if (type != 0) return vec4(0.0);
        if (pass_index == 1) return src(uv);
        return pass_index <= 12 ? bloom_down(uv, pass_index - 1) : bloom_up(uv, 23 - pass_index);
    }

    vec3 g;
    if (pass_index == 126) {                                   // the light: gathered, then its saturation, colour and strength
        vec2 R = resolution;
        float q = quality == 0 ? 1.0 : quality == 1 ? 2.0 : 4.0;
        g = type == 0 ? bloom(uv) : type == 1 ? ghosts(uv, R, q) : type == 2 ? streaks_of(uv, R, q)
          : type == 3 ? fog_glow(uv, R, q) : type == 4 ? simple_star(uv, R, q) : sun_beams(uv, R, q);
        vec3 hsv = rgb2hsv(max(g, vec3(0.0)));                 // saturation as Blender mixes it
        hsv.y = clamp(hsv.y * max(saturation, 0.0), 0.0, 1.0);
        // (Bloom adds one picture per step of its chain, so Blender divides by the chain's length)
        g = hsv2rgb(hsv) * srgb_to_lin(tint.rgb) * (max(strength, 0.0) / (type == 0 ? float(max(1, bloom_length())) : 1.0));
        return vec4(g, 1.0);
    }
    if (output_index == 2) {                                   // pass 127, 亮部: what glows, alone (Blender's Highlights output)
        vec3 h = quality == 0 ? max(highlights(linear(original(uv)).rgb), vec3(0.0)) : reduced_highlights_at(uv);    // (品質 中 / 低: the reduced picture's, as Blender gives it)
        float ha = clamp(max(h.r, max(h.g, h.b)), 0.0, 1.0);
        return ha > 0.0 ? vec4(lin_to_srgb(h / ha) * ha, ha) : vec4(0.0);
    }
    float sg = grain_sigma();                                  // pass 127: smooth the grain, add the light to the picture
    if (sg > 0.0) {
        vec2 px = 1.0 / pass_px;
        vec3 acc = vec3(0.0);
        float wsum = 0.0;
        for (int j = -3; j <= 3; j++)
            for (int i = -3; i <= 3; i++) {
                float w = exp(-float(i * i + j * j) / (2.0 * sg * sg));
                acc += w * src(uv + vec2(float(i), float(j)) * px).rgb;
                wsum += w;
            }
        g = acc / wsum;
    } else {
        g = src(uv).rgb;
    }

    if (output_index == 1) {                                   // 光: the light alone (Blender's Glare output)
        float ga = clamp(max(g.r, max(g.g, g.b)), 0.0, 1.0);
        return ga > 0.0 ? vec4(lin_to_srgb(g / ga) * ga, ga) : vec4(0.0);
    }

    // the light is added to the picture (premultiplied, linear); where it is brighter than the
    // picture is opaque, it lights that spot itself - the glow spreads over what was clear
    vec4 c = linear(original(uv));
    float a = clamp(c.a, 0.0, 1.0);
    vec3 t = max(c.rgb + g, vec3(0.0));
    float A = clamp(max(a, max(t.r, max(t.g, t.b))), 0.0, 1.0);
    vec3 rgb = A > 0.0 ? lin_to_srgb(t / A) * A : vec3(0.0);
    return vec4(min(rgb, vec3(A)), A);
}

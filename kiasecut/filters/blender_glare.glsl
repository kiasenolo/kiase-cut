// @filter [Blender] Glare
// @category Blender
// @description Blender 合成器的 Glare：亮部的光暈、鬼影、光芒、霧光、星芒、光束（在線性光裡運算）
// @output image "圖像"
// @output glare "光"
// @output highlights "亮部"
// @passes 26
// @levels 0f 0 1 2 3 4 5 6 7 8 9 10 11 10 9 8 7 6 5 4 3 2 1 0 quality
// @extras - - - - - 0 - - - - - - - 11 10 9 8 7 6 5 4 3 2 1 0 -
// @shared
// @alone highlights
// @skip 1-4 type != Bloom
// @skip 5 type != Bloom|Sun Beams
// @skip 6-23 type != Bloom
// @precision float
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

// (Sun Beams uses pass 5 - 1 / 16 of the canvas, 1 / 32, 1 / 64 for 中, 低 - for a map of the blocks of the highlights that
// hold any light, and the passes of Bloom's chain that are not drawn for it are left out: see sun_occupancy.)
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

vec3 ghosts(vec2 uv, vec2 R, float q) {
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
            vec2 o = rr * vec2(cos(6.2831853 * rq.y), sin(6.2831853 * rq.y)) * (16.0 / 3.0) * q / R;
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

// Sun Beams, pass 5: 1 where a block of the highlights (pass 0, extra()) holds any light - its margin of 2 pixels counts, a
// read takes the four pixels around a point - else 0. Highlights are never negative, so any light is a sum above 0.
vec4 sun_occupancy(vec2 uv) {
    vec2 cell = extra_px / pass_px;                            // highlight pixels per block
    ivec2 b = ivec2(floor(uv * pass_px));
    ivec2 last = ivec2(extra_px) - 1;
    ivec2 lo = max(ivec2(floor(vec2(b) * cell)) - 2, ivec2(0)), hi = min(ivec2(ceil(vec2(b + 1) * cell)) + 2, last);
    for (int y = lo.y; y <= hi.y; y++)
        for (int x = lo.x; x <= hi.x; x++)
            if (dot(texelFetch(extra_, ivec2(x, y), 0).rgb, vec3(1.0)) > 0.0) return vec4(1.0);
    return vec4(0.0);
}

vec3 sun_beams(vec2 uv, vec2 R, float q) {
    // along the line to the sun, one step per glare pixel (q canvas px; never finer than this pass's own pixels):
    // every step is read, so the picture stays free of grain however fine the highlights are - but a run of steps
    // that lies in blocks with no light (pass 5's map, src()) adds nothing, so it is not read; the weights' sum, the same
    // for every pixel with this many steps, is worked out whole (n (4 n^2 - 1) / 12 over n^2)
    float k = pass_px.x / R.x;                                 // this pass's px per canvas px
    vec2 P = uv * pass_px;
    vec2 v = vec2(sun_position.x, 1.0 - sun_position.y) * pass_px - P;     // (y up from the bottom, as Blender's: pictures are stored top row first)
    float dist = length(v);
    vec2 dir = v / max(dist, 1e-6);
    float L = min(max(size, 0.0) * length(pass_px), dist);
    float step_px = max(1.0, q * k);
    int steps = int(clamp(ceil(L / step_px), 1.0, 2304.0));
    float n = float(steps);
    float wsum = (4.0 * n * n - 1.0) / (12.0 * n);
    vec2 map = src_px;
    int run = max(1, int(floor(min(extra_px.x / map.x, extra_px.y / map.y) / step_px)));    // steps that fit in a block
    vec3 acc = vec3(0.0);
    for (int c = 0; c < steps; c += run) {
        int e = min(c + run, steps) - 1;
        vec2 pa = (P + dir * ((float(c) + 0.5) / n * L)) / pass_px, pb = (P + dir * ((float(e) + 0.5) / n * L)) / pass_px;
        vec2 lo = min(pa, pb), hi = max(pa, pb);
        if (hi.x < 0.0 || hi.y < 0.0 || lo.x > 1.0 || lo.y > 1.0) continue;
        ivec2 ba = clamp(ivec2(floor(lo * map)), ivec2(0), ivec2(map) - 1), bb = clamp(ivec2(floor(hi * map)), ivec2(0), ivec2(map) - 1);
        bool lit = false;
        for (int y = ba.y; y <= bb.y; y++)
            for (int x = ba.x; x <= bb.x; x++)
                lit = lit || texelFetch(source, ivec2(x, y), 0).r > 0.0;
        if (!lit)
            continue;
        for (int i = c; i <= e; i++) {
            float t = (float(i) + 0.5) / n;
            acc += (1.0 - t) * (1.0 - t) * H((P + dir * t * L) / pass_px);
        }
    }
    return acc / max(wsum, 1e-6);
}

// the gathered light's grain (the types that read at random spots - ghosts, fog glow, sun beams, long
// streaks - leave some) is smoothed over a few pixels of this very picture: a small Gaussian
float grain_sigma() {
    if (type == 3) return 2.0;
    if (type == 1) return 1.6;
    if (type == 2 && streak_skip() > 0) return 1.1;
    return 0.0;
}

vec4 effect(vec2 uv) {
    if (pass_index == 0)
        return vec4(max(highlights(linear(src(uv)).rgb), vec3(0.0)), 1.0);
    if (pass_index == 5 && type == 5) return sun_occupancy(uv);
    if (pass_index < 24) {                                     // (Bloom's chain; the other types leave it empty)
        if (type != 0) return vec4(0.0);
        if (pass_index == 1) return src(uv);
        return pass_index <= 12 ? bloom_down(uv, pass_index - 1) : bloom_up(uv, 23 - pass_index);
    }

    vec3 g;
    if (pass_index == 24) {                                    // the light: gathered, then its saturation, colour and strength
        vec2 R = resolution;
        float q = quality == 0 ? 1.0 : quality == 1 ? 2.0 : 4.0;
        g = type == 0 ? bloom(uv) : type == 1 ? ghosts(uv, R, q) : type == 2 ? streak_lines(uv, R, q)
          : type == 3 ? fog_glow(uv, R, q) : type == 4 ? simple_star(uv, R, q) : sun_beams(uv, R, q);
        vec3 hsv = rgb2hsv(max(g, vec3(0.0)));                 // saturation as Blender mixes it
        hsv.y = clamp(hsv.y * max(saturation, 0.0), 0.0, 1.0);
        // (Bloom adds one picture per step of its chain, so Blender divides by the chain's length)
        g = hsv2rgb(hsv) * srgb_to_lin(tint.rgb) * (max(strength, 0.0) / (type == 0 ? float(max(1, bloom_length())) : 1.0));
        return vec4(g, 1.0);
    }
    if (output_index == 2) {                                   // pass 25, 亮部: what glows, alone (Blender's Highlights output)
        vec3 h = max(highlights(linear(original(uv)).rgb), vec3(0.0));
        float ha = clamp(max(h.r, max(h.g, h.b)), 0.0, 1.0);
        return ha > 0.0 ? vec4(lin_to_srgb(h / ha) * ha, ha) : vec4(0.0);
    }
    float sg = grain_sigma();                                  // pass 25: smooth the grain, add the light to the picture
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

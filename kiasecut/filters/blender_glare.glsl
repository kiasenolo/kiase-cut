// @filter [Blender] Glare
// @category Blender
// @description Blender 合成器的 Glare：亮部的光暈、鬼影、光芒、霧光、星芒、光束（在線性光裡運算）
// @passes 2
// @param type menu Bloom "Bloom|Ghosts|Streaks|Fog Glow|Simple Star|Sun Beams" "類型"
// @param quality menu 中 "高|中|低" "品質"
// @param threshold float 0.7 0 1 "亮度門檻"
// @param smoothness float 0.1 0 1 "門檻柔邊"
// @param clamp_on bool false "限制亮度"
// @param maximum float 1 0 1 "最大亮度"
// @param strength float 1 0 4 "強度"
// @param saturation float 1 0 1 "飽和度"
// @param tint color #ffffff "光的顏色"
// @param size float 0.5 0 1 "大小"
// @param streaks int 4 1 16 "光芒數"
// @param streak_angle float 0 -180 180 "光芒角度"
// @param iterations int 3 2 5 "光芒長度"
// @param fade float 0.9 0.75 1 "光芒衰減"
// @param color_modulation float 0.25 0 1 "色彩調變"
// @param diagonal bool true "斜向星芒"
// @param sun_position vec2 0.5,0.5 0 1 "光源位置"

// Pass 0 keeps the highlights (what glows, as Blender computes it); pass 1 spreads them by the
// chosen type, each sample one read of pass 0, and adds them to the picture. 品質 中 / 低 spread
// over every 2nd / 4th canvas pixel, as Blender's Medium / Low work on a picture 2 / 4 times smaller.

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

// pass 0's highlights at p (stored as square roots: more precision for the dark end of 8 bits); none outside
vec3 H(vec2 p) {
    if (p.x < 0.0 || p.y < 0.0 || p.x > 1.0 || p.y > 1.0) return vec3(0.0);
    vec3 e = src(p).rgb;
    return e * e;
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

vec3 bloom(vec2 uv, vec2 R) {
    float Lf = floor(log2(max(min(R.x, R.y) * clamp(size, 0.0, 1.0), 1.0)));
    if (Lf < 1.0) return H(uv);
    int nl = int(clamp(Lf, 3.0, 10.0));
    float rot = hash31(vec3(gl_FragCoord.xy, 5.0)), jr = hash31(vec3(gl_FragCoord.xy, 6.0));
    int ns = max(quality == 0 ? 48 : quality == 1 ? 32 : 20, nl);
    vec3 acc = vec3(0.0);
    for (int i = 0; i < ns; i++) {              // Gaussians of radius 2^level, every level ~ns/nl samples
        vec2 q = r2(i, jr, rot);
        float lv = min(floor((float(i) + jr) / float(ns) * float(nl)), float(nl - 1));
        float rr = (Lf < 3.0 ? 0.9 : 1.2) * exp2(lv) * sqrt(-2.0 * log(max(1.0 - q.x, 1e-4)));
        float an = 6.2831853 * q.y;
        acc += H(uv + rr * vec2(cos(an), sin(an)) / R);
    }
    return acc / float(ns);
}

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

vec3 streak_lines(vec2 uv, vec2 R, float q) {
    float fd = clamp(fade, 0.75, 1.0);
    float cm = clamp(color_modulation, 0.0, 1.0);
    int N = clamp(iterations, 2, 5);
    int ns = clamp(streaks, 1, 16);
    float total = exp2(2.0 * float(N));
    float nmax = fd < 1.0 ? min(total, ceil(log(1e-3) / log(fd))) : total;
    float per = float(max(min(64, 512 / ns), 4));
    // Blender's streak after N iterations, read every st-th pixel (the skipped ones folded into wlow)
    int m = 0;
    while (m < N && nmax / exp2(2.0 * float(m)) > per) m++;
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

vec3 sun_beams(vec2 uv, vec2 R) {
    vec2 P = uv * R;
    vec2 v = sun_position * R - P;
    float dist = length(v);
    vec2 dir = v / max(dist, 1e-6);
    float L = min(max(size, 0.0) * length(R), dist);
    float jit = hash31(vec3(gl_FragCoord.xy, 3.0));
    int steps = quality == 0 ? 32 : quality == 1 ? 24 : 16;
    vec3 acc = vec3(0.0);
    float wsum = 0.0;
    for (int i = 0; i < steps; i++) {
        float t = (float(i) + jit) / float(steps);
        float w = (1.0 - t) * (1.0 - t);
        acc += w * H((P + dir * t * L) / R);
        wsum += w;
    }
    return acc / max(wsum, 1e-6);
}

vec4 effect(vec2 uv) {
    if (pass_index == 0)
        return vec4(sqrt(clamp(highlights(linear(src(uv)).rgb), 0.0, 1.0)), 1.0);

    vec2 R = resolution;
    float q = quality == 0 ? 1.0 : quality == 1 ? 2.0 : 4.0;
    vec3 g = type == 0 ? bloom(uv, R) : type == 1 ? ghosts(uv, R, q) : type == 2 ? streak_lines(uv, R, q)
           : type == 3 ? fog_glow(uv, R, q) : type == 4 ? simple_star(uv, R, q) : sun_beams(uv, R);
    vec3 hsv = rgb2hsv(max(g, vec3(0.0)));                     // saturation as Blender mixes it
    hsv.y = clamp(hsv.y * max(saturation, 0.0), 0.0, 1.0);
    g = hsv2rgb(hsv) * srgb_to_lin(tint.rgb) * max(strength, 0.0);

    vec4 c = linear(original(uv));
    float a = clamp(c.a, 0.0, 1.0);
    vec3 rgb = a > 0.0 ? lin_to_srgb((c.rgb + g) / a) * a : vec3(0.0);
    return vec4(min(rgb, vec3(a)), a);
}

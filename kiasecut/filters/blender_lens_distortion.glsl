// @filter [Blender] Lens Distortion
// @category Blender
// @description Blender 合成器的 Lens Distortion：鏡頭的桶狀／枕狀變形和色散；「水平」是投影機式的左右色散（在線性光裡運算）
// @param mode menu 放射 "放射|水平" "類型"
// @param distortion float 0 -0.999 1 "變形"
// @param dispersion float 0 0 1 "色散"
// @param jitter bool false "抖動取樣"
// @param fit bool false "填滿畫面"

vec3 srgb_to_lin(vec3 c) { return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(vec3(0.04045), c)); }
vec3 lin_to_srgb(vec3 c) { c = clamp(c, 0.0, 1.0); return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(vec3(0.0031308), c)); }
float hash31(vec3 p) { p = fract(p * 0.1031); p += dot(p, p.zyx + 31.32); return fract((p.x + p.y) * p.z); }

// linear, premultiplied; nothing outside the picture (Blender leaves it empty)
vec4 lin(vec2 p) {
    if (p.x < 0.0 || p.y < 0.0 || p.x > 1.0 || p.y > 1.0) return vec4(0.0);
    vec4 c = unpremultiply(src(p));
    return vec4(srgb_to_lin(c.rgb) * c.a, c.a);
}

vec4 encode(vec4 c) {
    float a = clamp(c.a, 0.0, 1.0);
    vec3 rgb = a > 0.0 ? lin_to_srgb(c.rgb / a) * a : vec3(0.0);
    return vec4(min(rgb, vec3(a)), a);
}

vec2 bend(vec2 p, float r2, float k) { return p / (1.0 + sqrt(max(1.0 - k * r2, 0.0))) + 0.5; }

vec4 effect(vec2 uv) {
    float dp = clamp(dispersion, 0.0, 1.0);
    if (mode == 1) {                          // 水平 (Blender's projector): red and blue 5 px apart per unit of dispersion
        vec2 o = vec2(5.0 * dp / resolution.x, 0.0);
        vec4 g = lin(uv);
        return encode(vec4(lin(uv + o).r, g.g, lin(uv - o).b, g.a));
    }
    float k = clamp(distortion, -0.999, 1.0);
    float ke = k + 0.25 * dp;
    float sc = (fit && ke > 0.0) ? 1.0 / (1.0 + 2.0 * ke) : 1.0 / (1.0 + ke);
    vec2 p = (uv * 2.0 - 1.0) * sc;
    float r2 = dot(p, p);
    float kr = 4.0 * k + 0.7 * dp, kb = 4.0 * k - 0.7 * dp;
    vec4 cg = lin(bend(p, r2, 4.0 * k));
    if (dp <= 0.0)
        return encode(cg);
    // the spectrum from red to blue in 8 steps (jitter: each pixel's steps shifted at random)
    float j = jitter ? hash31(vec3(gl_FragCoord.xy, 4.0)) : 0.5;
    vec3 acc = vec3(0.0), wsum = vec3(0.0);
    for (int i = 0; i < 8; i++) {
        float t = (float(i) + j) / 8.0;
        vec3 w = vec3(max(1.0 - 2.0 * t, 0.0), 1.0 - abs(2.0 * t - 1.0), max(2.0 * t - 1.0, 0.0));
        acc += lin(bend(p, r2, mix(kr, kb, t))).rgb * w;
        wsum += w;
    }
    return encode(vec4(acc / max(wsum, vec3(1e-4)), cg.a));
}

// @filter Glich Effect
// @category 風格
// @description 每一行的紅、綠、藍各自隨機左右錯開（在線性光裡運算）
// @param base_offset float -0.5 -2 2 "基準偏移"
// @param shake float 25 -500 500 "晃動幅度"
// @param animated bool false "每格不同"
// @param seed float 0 0 100 "種子"
// @param posterize bool false "分段"
// @param steps float 8 2 256 "段數"

vec3 srgb_to_lin(vec3 c) { return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(vec3(0.04045), c)); }
vec3 lin_to_srgb(vec3 c) { c = clamp(c, 0.0, 1.0); return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(vec3(0.0031308), c)); }
float hash31(vec3 p) { p = fract(p * 0.1031); p += dot(p, p.zyx + 31.32); return fract((p.x + p.y) * p.z); }
float white3(vec3 p) { return hash31(floor(p * 4096.0)); }

// linear, premultiplied; nothing outside the picture
vec4 lin(vec2 p) {
    if (p.x < 0.0 || p.x > 1.0) return vec4(0.0);
    vec4 c = unpremultiply(src(p));
    return vec4(srgb_to_lin(c.rgb) * c.a, c.a);
}

vec4 effect(vec2 uv) {
    // a row is about a canvas pixel high (Blender's image coordinates, -1..1 on the long side, x 2048);
    // 分段: bands of 1 / steps of them instead
    float y = (1.0 - 2.0 * uv.y) * resolution.y / max(resolution.x, resolution.y);
    if (posterize) {
        float st = clamp(steps, 2.0, 1024.0);
        y = floor(y * st) / st;
    }
    vec3 q = vec3(0.0, y, seed + (animated ? float(frame) : 0.0));
    vec3 n = vec3(white3(q), white3(q + vec3(17.1, 3.7, 9.3)), white3(q + vec3(5.3, 21.9, 1.3)));
    vec3 dx = (n + base_offset) * shake / resolution.x;        // each channel's shift, canvas px -> uv

    float a = clamp(src(uv).a, 0.0, 1.0);
    vec3 c = vec3(lin(uv - vec2(dx.r, 0.0)).r, lin(uv - vec2(dx.g, 0.0)).g, lin(uv - vec2(dx.b, 0.0)).b);
    vec3 rgb = a > 0.0 ? lin_to_srgb(c / a) * a : vec3(0.0);
    return vec4(min(rgb, vec3(a)), a);
}

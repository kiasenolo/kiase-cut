// @filter 素描
// @category 風格
// @description 只留下輪廓線，像鉛筆畫
// @param strength float 1.5 0 6 "線條強度"
// @param thickness float 1 0.5 6 "線條粗細"
// @param neon bool false "黑底亮線"
// @param amount float 1 0 1 "程度"
float lum(vec2 p) {
    return dot(src(p).rgb, vec3(0.299, 0.587, 0.114));
}
vec4 effect(vec2 uv) {
    vec2 px = vec2(thickness * scale) / resolution;
    float tl = lum(uv + px * vec2(-1.0, -1.0)), t = lum(uv + px * vec2(0.0, -1.0)), tr = lum(uv + px * vec2(1.0, -1.0));
    float l = lum(uv + px * vec2(-1.0, 0.0)), r = lum(uv + px * vec2(1.0, 0.0));
    float bl = lum(uv + px * vec2(-1.0, 1.0)), b = lum(uv + px * vec2(0.0, 1.0)), br = lum(uv + px * vec2(1.0, 1.0));
    float gx = (tr + 2.0 * r + br) - (tl + 2.0 * l + bl);
    float gy = (bl + 2.0 * b + br) - (tl + 2.0 * t + tr);
    float e = clamp(length(vec2(gx, gy)) * strength, 0.0, 1.0);
    vec4 c = unpremultiply(src(uv));
    vec3 lines = neon ? vec3(e) : vec3(1.0 - e);
    return premultiply(vec4(mix(c.rgb, lines, amount), c.a));
}

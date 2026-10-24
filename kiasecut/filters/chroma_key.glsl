// @filter 色度去背
// @category 去背
// @description 綠幕、藍幕去背：接近選定顏色的地方變透明
// @param key color #00ff00 "去背顏色"
// @param tolerance float 0.15 0 0.6 "容許範圍"
// @param softness float 0.08 0 0.5 "邊緣柔和"
// @param spill float 0.5 0 1 "去除溢色"
vec2 chroma(vec3 c) {
    return vec2(dot(c, vec3(-0.168736, -0.331264, 0.5)), dot(c, vec3(0.5, -0.418688, -0.081312)));
}
vec4 effect(vec2 uv) {
    vec4 c = unpremultiply(src(uv));
    float d = distance(chroma(c.rgb), chroma(key.rgb));
    float a = smoothstep(tolerance, tolerance + softness + 1e-4, d);
    float near = 1.0 - smoothstep(tolerance, tolerance + softness + 0.25, d);
    float l = dot(c.rgb, vec3(0.299, 0.587, 0.114));
    vec3 rgb = mix(c.rgb, vec3(l), near * spill);   // the key colour bleeding onto edges goes grey
    return premultiply(vec4(rgb, c.a * a));
}

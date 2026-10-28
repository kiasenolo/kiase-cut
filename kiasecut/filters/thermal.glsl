// @filter 熱成像
// @category 色彩
// @description 熱感應攝影機的假色：暗的地方是冷色，亮的地方是熱色
// @param palette menu 鐵紅 "鐵紅|彩虹|白熱" "色盤"
// @param contrast float 1.2 0.2 4 "對比"
// @param amount float 1 0 1 "程度"

vec3 iron(float t) {
    vec3 c = mix(vec3(0.0, 0.0, 0.08), vec3(0.35, 0.0, 0.55), smoothstep(0.0, 0.25, t));
    c = mix(c, vec3(0.85, 0.1, 0.25), smoothstep(0.2, 0.5, t));
    c = mix(c, vec3(1.0, 0.55, 0.0), smoothstep(0.45, 0.75, t));
    return mix(c, vec3(1.0, 1.0, 0.85), smoothstep(0.75, 1.0, t));
}
vec3 rainbow(float t) {
    vec3 c = mix(vec3(0.0, 0.0, 0.5), vec3(0.0, 0.4, 1.0), smoothstep(0.0, 0.2, t));
    c = mix(c, vec3(0.0, 1.0, 0.6), smoothstep(0.2, 0.4, t));
    c = mix(c, vec3(1.0, 1.0, 0.0), smoothstep(0.4, 0.6, t));
    c = mix(c, vec3(1.0, 0.2, 0.0), smoothstep(0.6, 0.85, t));
    return mix(c, vec3(1.0), smoothstep(0.85, 1.0, t));
}

vec4 effect(vec2 uv) {
    vec4 c = unpremultiply(src(uv));
    float l = dot(c.rgb, vec3(0.299, 0.587, 0.114));
    float t = clamp((l - 0.5) * contrast + 0.5, 0.0, 1.0);
    vec3 heat = palette == 0 ? iron(t) : palette == 1 ? rainbow(t) : vec3(t);
    return premultiply(vec4(mix(c.rgb, heat, amount), c.a));
}

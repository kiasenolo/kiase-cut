// @filter 暗角
// @category 風格
// @description 四周變暗
// @param strength float 0.6 0 1 "強度"
// @param softness float 0.5 0.01 1 "柔和度"
vec4 effect(vec2 uv) {
    vec4 c = src(uv);
    vec2 d = (uv - 0.5) * vec2(resolution.x / resolution.y, 1.0);
    float v = smoothstep(0.9 - softness * 0.9, 0.9 + softness * 0.4, length(d) * 1.4142);
    return vec4(c.rgb * (1.0 - strength * v), c.a);
}

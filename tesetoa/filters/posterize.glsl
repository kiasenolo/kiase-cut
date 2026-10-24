// @filter 色階分離
// @category 色彩
// @description 每個通道只留幾個色階
// @param levels float 6 2 32 "色階數"
vec4 effect(vec2 uv) {
    vec4 c = unpremultiply(src(uv));
    vec3 rgb = floor(c.rgb * levels + 0.5) / levels;
    return premultiply(vec4(rgb, c.a));
}

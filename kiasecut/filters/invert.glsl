// @filter 反相
// @category 色彩
// @description 顏色反轉
// @param amount float 1 0 1 "程度"
vec4 effect(vec2 uv) {
    vec4 c = unpremultiply(src(uv));
    return premultiply(vec4(mix(c.rgb, 1.0 - c.rgb, amount), c.a));
}

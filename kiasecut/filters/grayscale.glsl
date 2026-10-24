// @filter 黑白
// @category 色彩
// @description 去掉顏色，只留明暗
// @param amount float 1 0 1 "程度"
vec4 effect(vec2 uv) {
    vec4 c = unpremultiply(src(uv));
    float l = dot(c.rgb, vec3(0.299, 0.587, 0.114));
    return premultiply(vec4(mix(c.rgb, vec3(l), amount), c.a));
}

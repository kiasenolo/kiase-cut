// @filter 雙色調
// @category 色彩
// @description 暗部換成一個顏色、亮部換成另一個顏色
// @param dark color #1b1464 "暗部顏色"
// @param light color #ffb347 "亮部顏色"
// @param amount float 1 0 1 "程度"
vec4 effect(vec2 uv) {
    vec4 c = unpremultiply(src(uv));
    float l = dot(c.rgb, vec3(0.299, 0.587, 0.114));
    return premultiply(vec4(mix(c.rgb, mix(dark.rgb, light.rgb, l), amount), c.a));
}

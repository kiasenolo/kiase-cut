// @filter 曝光與高光陰影
// @category 色彩
// @description 曝光（以檔為單位），另外單獨拉亮或壓暗亮部和暗部
// @param exposure float 0 -3 3 "曝光"
// @param highlights float 0 -1 1 "高光"
// @param shadows float 0 -1 1 "陰影"
vec4 effect(vec2 uv) {
    vec4 c = unpremultiply(src(uv));
    vec3 rgb = c.rgb * exp2(exposure);
    float l = dot(clamp(rgb, 0.0, 1.0), vec3(0.299, 0.587, 0.114));
    float sh = 1.0 - smoothstep(0.0, 0.55, l);
    float hl = smoothstep(0.45, 1.0, l);
    rgb += shadows * 0.35 * sh + highlights * 0.35 * hl;
    return premultiply(vec4(clamp(rgb, 0.0, 1.0), c.a));
}

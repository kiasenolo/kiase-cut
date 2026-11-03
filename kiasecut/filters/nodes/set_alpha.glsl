// @filter 設定透明度
// @category 節點
// @description 節點用：用另一張圖的明度當圖像的透明度（原本的透明度會乘上去）
// @source 圖像
// @input alpha_img "透明度"
// @param fac float 1 0 1 "係數"

vec4 effect(vec2 uv) {
    vec4 c = unpremultiply(src(uv)), m = input_alpha_img(uv);
    float k = m.a > 0.0 ? clamp(dot(m.rgb, vec3(0.2126, 0.7152, 0.0722)), 0.0, 1.0) : 0.0;
    return premultiply(vec4(c.rgb, c.a * mix(1.0, k, fac)));
}

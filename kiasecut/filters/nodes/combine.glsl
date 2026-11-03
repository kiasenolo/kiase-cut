// @filter 合併通道
// @category 節點
// @description 節點用：四張圖的明度分別當紅、綠、藍、透明度（沒接透明度就是不透明）
// @source 紅
// @input g "綠"
// @input b "藍"
// @input a "透明度"

float luma_of(vec4 p) {
    return p.a > 0.0 ? dot(p.rgb, vec3(0.2126, 0.7152, 0.0722)) : 0.0;
}

vec4 effect(vec2 uv) {
    vec4 pa = input_a(uv);
    float alpha = pa.a > 0.0 ? clamp(luma_of(pa), 0.0, 1.0) : 1.0;
    return premultiply(vec4(luma_of(src(uv)), luma_of(input_g(uv)), luma_of(input_b(uv)), alpha));
}

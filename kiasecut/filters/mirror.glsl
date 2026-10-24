// @filter 鏡像
// @category 扭曲
// @description 翻轉畫面，或把一半鏡射到另一半變成對稱
// @param flip_x bool true "左右翻轉"
// @param flip_y bool false "上下翻轉"
// @param sym_x bool false "左右對稱"
// @param sym_y bool false "上下對稱"
vec4 effect(vec2 uv) {
    vec2 p = uv;
    if (flip_x) p.x = 1.0 - p.x;
    if (flip_y) p.y = 1.0 - p.y;
    if (sym_x && p.x > 0.5) p.x = 1.0 - p.x;
    if (sym_y && p.y > 0.5) p.y = 1.0 - p.y;
    return src(p);
}

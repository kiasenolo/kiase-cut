// @filter 電影寬螢幕
// @category 風格
// @description 上下（或左右）加黑邊，變成電影的畫面比例
// @param ratio float 2.39 0.5 4 "畫面比例（寬 ÷ 高）"
// @param color color #000000 "邊的顏色"
vec4 effect(vec2 uv) {
    float aspect = resolution.x / resolution.y;
    bool bar = ratio > aspect ? abs(uv.y - 0.5) > 0.5 * aspect / ratio
                              : abs(uv.x - 0.5) > 0.5 * ratio / aspect;
    return bar ? premultiply(color) : src(uv);
}

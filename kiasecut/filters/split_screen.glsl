// @filter 分屏
// @category 扭曲
// @description 同一個畫面排成幾欄幾列
// @param columns int 2 1 8 "欄數"
// @param rows int 2 1 8 "列數"
// @param mirrored bool false "相鄰的鏡射"
vec4 effect(vec2 uv) {
    vec2 n = vec2(float(max(columns, 1)), float(max(rows, 1)));
    vec2 cell = floor(uv * n);
    vec2 p = fract(uv * n);
    if (mirrored) p = mix(p, 1.0 - p, mod(cell, 2.0));
    return src(p);
}

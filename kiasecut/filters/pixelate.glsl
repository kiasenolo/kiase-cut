// @filter 像素化
// @category 風格
// @description 把畫面變成馬賽克方塊
// @param size float 16 1 200 "方塊大小"
vec4 effect(vec2 uv) {
    vec2 cell = vec2(max(size, 1.0)) / resolution;
    vec2 p = (floor(uv / cell) + 0.5) * cell;
    return src(p);
}

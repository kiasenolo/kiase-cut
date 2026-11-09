// @filter Translate
// @category 變形
// @description 依畫布像素平移畫面，超出範圍的部分為透明
// @param offset vec2 0,0 -10000 10000 "位移（px）"

vec4 effect(vec2 uv) {
    vec2 p = uv - offset / resolution;
    if (!in_picture(p)) return vec4(0.0);
    return src(p);
}

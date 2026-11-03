// @filter 變換
// @category 變換
// @description 節點用：移動、旋轉、縮放圖像（以畫布像素為單位，繞畫面中心）
// @param offset vec2 0,0 -10000 10000 "位置"
// @param rotation float 0 -3600 3600 "旋轉"
// @param zoom float 1 0.001 1000 "縮放"

vec4 effect(vec2 uv) {
    vec2 p = (uv - 0.5) * resolution - vec2(offset.x, -offset.y);
    float a = radians(rotation), cs = cos(a), sn = sin(a);
    p = vec2(cs * p.x - sn * p.y, sn * p.x + cs * p.y) / zoom;
    vec2 q = p / resolution + 0.5;
    if (q.x < 0.0 || q.y < 0.0 || q.x > 1.0 || q.y > 1.0) return vec4(0.0);
    return src(q);
}

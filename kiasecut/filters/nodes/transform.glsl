// @filter 變換
// @category 變換
// @description 節點用：照 Blender 的「變換」：先縮放、再旋轉、最後移動圖像（以畫布像素為單位，繞畫面中心，Y 向上），取樣可選最近點、雙線性、雙三次
// @param pos_x float 0 -10000 10000 "X"
// @param pos_y float 0 -10000 10000 "Y"
// @param angle float 0 -3600 3600 "角度"
// @param zoom float 1 0.001 1000 "縮放"
// @param interp menu 雙線性 "最近點|雙線性|雙三次" "取樣"

vec4 cubic_tap(vec2 q) {                            // (Catmull-Rom over the 16 nearest pixels)
    vec2 px = src_px, f = q * px - 0.5, i = floor(f), t = f - i;
    vec2 t2 = t * t, t3 = t2 * t;
    vec2 w0 = -0.5 * t3 + t2 - 0.5 * t, w1 = 1.5 * t3 - 2.5 * t2 + 1.0, w2 = -1.5 * t3 + 2.0 * t2 + 0.5 * t, w3 = 0.5 * t3 - 0.5 * t2;
    vec2 ws[4] = vec2[4](w0, w1, w2, w3);
    vec4 acc = vec4(0.0);
    for (int y = 0; y < 4; y++)
        for (int x = 0; x < 4; x++)
            acc += src((i + vec2(float(x) - 1.0, float(y) - 1.0) + 0.5) / px) * ws[x].x * ws[y].y;
    return clamp(acc, 0.0, 1.0);
}

vec4 effect(vec2 uv) {
    vec2 p = (uv - 0.5) * resolution - vec2(pos_x, -pos_y);
    float a = radians(angle), cs = cos(a), sn = sin(a);
    p = vec2(cs * p.x - sn * p.y, sn * p.x + cs * p.y) / zoom;
    vec2 q = p / resolution + 0.5;
    if (q.x < 0.0 || q.y < 0.0 || q.x > 1.0 || q.y > 1.0) return vec4(0.0);
    if (interp == 0) return src((floor(q * src_px) + 0.5) / src_px);
    if (interp == 2) return cubic_tap(q);
    return src(q);
}

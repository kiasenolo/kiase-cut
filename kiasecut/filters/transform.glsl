// @filter Transform
// @category 變形
// @description 以錨點為中心調整位置、縮放與旋轉；錨點 0 在中央，±0.5 在邊緣，1 就是整個畫面的寬／高
// @param position vec2 0,0 -10000 10000 "位置（px）"
// @param factor vec2 1,1 0.01 20 "縮放"
// @param rotation float 0 -3600 3600 "旋轉 °"
// @param anchor vec2 0,0 -1 1 "錨點"

vec4 sample_image(vec2 p) {
    if (any(lessThan(p, vec2(0.0))) || any(greaterThan(p, vec2(1.0)))) return vec4(0.0);
    return src(p);
}

vec4 effect(vec2 uv) {
    vec2 pivot = vec2(0.5) + anchor;                 // (anchor: from the centre, in widths / heights of the picture)
    vec2 p = (uv - pivot) * resolution - position;
    float a = radians(rotation);
    p = mat2(cos(a), -sin(a), sin(a), cos(a)) * p;
    p /= max(factor, vec2(0.01));
    return sample_image(pivot + p / resolution);
}

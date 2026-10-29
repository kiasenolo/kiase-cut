// @filter Scale
// @category 變形
// @description 以錨點為中心縮放畫面；錨點 0 在中央，±0.5 在邊緣，1 就是整個畫面的寬／高
// @param factor vec2 1,1 0.01 20 "縮放"
// @param anchor vec2 0,0 -1 1 "錨點"

vec4 effect(vec2 uv) {
    vec2 pivot = vec2(0.5) + anchor;                 // (anchor: from the centre, in widths / heights of the picture)
    vec2 p = pivot + (uv - pivot) / max(factor, vec2(0.01));
    if (any(lessThan(p, vec2(0.0))) || any(greaterThan(p, vec2(1.0)))) return vec4(0.0);
    return src(p);
}

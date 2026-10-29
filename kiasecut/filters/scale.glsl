// @filter Scale
// @category 變形
// @description 以錨點為中心縮放畫面
// @param factor vec2 1,1 0.01 20 "縮放"
// @param anchor vec2 0.5,0.5 0 1 "錨點"

vec4 effect(vec2 uv) {
    vec2 p = anchor + (uv - anchor) / max(factor, vec2(0.01));
    if (any(lessThan(p, vec2(0.0))) || any(greaterThan(p, vec2(1.0)))) return vec4(0.0);
    return src(p);
}

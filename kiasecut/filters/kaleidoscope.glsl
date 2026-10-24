// @filter 萬花筒
// @category 扭曲
// @description 畫面切成扇形再鏡射，排成一圈
// @param segments float 6 2 24 "片數"
// @param rotation float 0 -360 360 "旋轉"
// @param center vec2 0.5,0.5 0 1 "中心"
vec4 effect(vec2 uv) {
    vec2 asp = vec2(resolution.x / resolution.y, 1.0);
    vec2 d = (uv - center) * asp;
    float seg = 6.2831853 / max(segments, 1.0);
    float a = mod(atan(d.y, d.x) + radians(rotation), seg);
    a = abs(a - 0.5 * seg);
    return src(center + vec2(cos(a), sin(a)) * length(d) / asp);
}

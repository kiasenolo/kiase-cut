// @filter 散景模糊
// @category 模糊
// @description 像鏡頭失焦的圓形模糊，亮點會散成一顆顆光斑
// @param radius float 12 0 60 "半徑"
// @param highlights float 0.5 0 1 "光斑亮度"
vec4 effect(vec2 uv) {
    if (radius < 0.5) return src(uv);
    // a disc of samples on a golden-angle spiral, turned a little per pixel; bright samples
    // weigh more, so lights spread into discs instead of being washed out
    float turn = rand(uv * resolution) * 6.2831853;
    vec4 sum = vec4(0.0);
    float total = 0.0;
    for (int i = 0; i < 96; i++) {
        float r = sqrt((float(i) + 0.5) / 96.0) * radius;
        float a = float(i) * 2.39996323 + turn;
        vec4 s = src(uv + vec2(cos(a), sin(a)) * r / resolution);
        float v = s.a > 0.0 ? max(s.r, max(s.g, s.b)) / s.a : 0.0;
        float w = 1.0 + highlights * 24.0 * pow(v, 6.0);
        sum += s * w;
        total += w;
    }
    return sum / total;
}

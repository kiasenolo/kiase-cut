// @filter 波浪
// @category 扭曲
// @description 畫面像水波一樣擺動
// @param amplitude float 12 0 100 "幅度"
// @param wavelength float 120 10 600 "波長"
// @param speed float 2 0 20 "速度"
vec4 effect(vec2 uv) {
    float k = 6.2831853 / (wavelength * scale);
    float dx = sin(uv.y * resolution.y * k + time * speed) * amplitude * scale / resolution.x;
    return src(vec2(uv.x + dx, uv.y));
}

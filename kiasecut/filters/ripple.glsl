// @filter 水波紋
// @category 扭曲
// @description 從一點往外擴散的一圈圈水波
// @param amplitude float 10 0 80 "幅度"
// @param wavelength float 60 5 400 "波長"
// @param speed float 1.5 0 10 "擴散速度"
// @param decay float 0.6 0 3 "往外衰減"
// @param center vec2 0.5,0.5 0 1 "中心"
vec4 effect(vec2 uv) {
    vec2 asp = vec2(resolution.x / resolution.y, 1.0);
    vec2 d = (uv - center) * asp;
    float r = length(d);
    if (r < 1e-5) return src(uv);
    float rpx = r * resolution.y;
    float phase = (rpx / wavelength - time * speed) * 6.2831853;
    float h = sin(phase) * exp(-r * decay * 3.0);
    vec2 at = uv + d / r / asp * h * amplitude / resolution.y;
    vec4 c = src(at);
    float shine = cos(phase) * exp(-r * decay * 3.0) * amplitude / 80.0;   // the slopes catch a little light
    return vec4(clamp(c.rgb + shine * 0.25 * c.a, 0.0, c.a), c.a);
}

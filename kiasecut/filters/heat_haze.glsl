// @filter 熱浪
// @category 扭曲
// @description 像隔著熱空氣看：畫面細細地扭動，往上飄
// @param amount float 6 0 60 "扭曲"
// @param size float 60 5 400 "波紋大小"
// @param speed float 1 0 10 "速度"

float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(rand(i), rand(i + vec2(1.0, 0.0)), f.x),
               mix(rand(i + vec2(0.0, 1.0)), rand(i + vec2(1.0, 1.0)), f.x), f.y);
}
float fbm(vec2 p) {
    return noise(p) * 0.6 + noise(p * 2.1 + 5.2) * 0.3 + noise(p * 4.3 + 9.7) * 0.1;
}

vec4 effect(vec2 uv) {
    vec2 p = uv * resolution / size;
    p.y += time * speed;                                 // rising
    vec2 o = vec2(fbm(p), fbm(p + vec2(17.3, 3.1))) - 0.5;
    return src(uv + o * 2.0 * amount / resolution);
}

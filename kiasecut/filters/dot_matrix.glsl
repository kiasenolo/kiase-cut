// @filter 點陣化
// @category 風格
// @description 把畫面變成一格一顆圓點的點陣（像 LED 看板）：每顆點取那一格的顏色
// @param size float 12 2 200 "點的間距"
// @param dot_size float 0.85 0 1 "點的大小"
// @param bright bool false "亮度影響大小"
// @param soft float 1 0 20 "邊緣柔化"
// @param background color #000000 "底色"
vec4 effect(vec2 uv) {
    float s = max(size, 1.0);
    vec2 px = uv * resolution;
    vec2 center = (floor(px / s) + 0.5) * s;
    vec4 c = src(center / resolution);
    float lum = dot(unpremultiply(c).rgb, vec3(0.2126, 0.7152, 0.0722));
    float r = 0.5 * s * dot_size * (bright ? mix(0.25, 1.0, lum) : 1.0);
    float a = 1.0 - smoothstep(r - soft, r + 0.001, length(px - center));
    vec4 d = c * a;
    vec4 bg = vec4(background.rgb * background.a, background.a);
    return d + bg * (1.0 - d.a);
}

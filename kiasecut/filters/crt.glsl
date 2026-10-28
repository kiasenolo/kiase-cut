// @filter CRT 螢幕
// @category 風格
// @description 老式映像管螢幕：畫面鼓起來、四角變暗，有掃描線和紅綠藍的螢光網格
// @param curvature float 0.3 0 1 "彎曲"
// @param scanlines float 0.5 0 1 "掃描線"
// @param lines float 270 50 1080 "掃描線數"
// @param mask float 0.4 0 1 "RGB 網格"
// @param vignette float 0.4 0 1 "暗角"
vec4 effect(vec2 uv) {
    vec2 p = uv * 2.0 - 1.0;
    p *= 1.0 + curvature * 0.25 * (p.yx * p.yx);       // barrel: the edges pulled outwards
    vec2 at = p * 0.5 + 0.5;
    if (any(lessThan(at, vec2(0.0))) || any(greaterThan(at, vec2(1.0)))) return vec4(0.0);
    vec4 c = src(at);
    // lines and stripes finer than the picture is drawn (a small preview) would only make
    // moire: they fade out below about 2 drawn pixels apart
    float sl = scanlines * smoothstep(1.5, 3.0, 1.0 / lines / fwidth(uv.y));
    float mk = mask * smoothstep(1.5, 3.0, 3.0 / resolution.x / fwidth(uv.x));
    float s = 0.5 + 0.5 * cos(at.y * lines * 6.2831853);
    vec3 rgb = c.rgb * (1.0 - sl * 0.6 * s);
    // aperture grille: red, green and blue stripes 1 canvas px each
    float x = uv.x * resolution.x / 3.0 * 6.2831853;
    vec3 grille = 0.5 + 0.5 * cos(vec3(x, x - 2.0944, x - 4.1888));
    rgb *= mix(vec3(1.0), grille * 1.6, mk * 0.6);
    rgb *= 1.0 + sl * 0.25 + mk * 0.1;                   // as bright as before on average
    vec2 e = at * (1.0 - at);
    float v = pow(clamp(e.x * e.y * 20.0, 0.0, 1.0), vignette * 0.6);
    float edge = smoothstep(0.0, 0.006, min(min(at.x, 1.0 - at.x), min(at.y, 1.0 - at.y)));
    return vec4(min(rgb * v, vec3(c.a)), c.a) * edge;
}

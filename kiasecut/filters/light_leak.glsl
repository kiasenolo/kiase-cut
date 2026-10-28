// @filter 漏光
// @category 光效
// @description 底片漏光：暖色的光斑從畫面邊緣慢慢飄進來，用濾色疊上去
// @param intensity float 0.7 0 1 "強度"
// @param color1 color #ff5a14 "顏色 1"
// @param color2 color #ffc46b "顏色 2"
// @param speed float 0.3 0 3 "飄動速度"
// @param seed float 0 0 100 "種子"

// smooth random wander, -1 to 1
float wobble(float x, float s) {
    float i = floor(x), f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(rand(vec2(i, s)), rand(vec2(i + 1.0, s)), f) * 2.0 - 1.0;
}

vec4 effect(vec2 uv) {
    vec4 c = src(uv);
    vec2 asp = vec2(resolution.x / resolution.y, 1.0);
    vec2 p = (uv - 0.5) * asp;
    float t = time * speed;
    vec3 light = vec3(0.0);
    for (int k = 0; k < 3; k++) {
        float s = seed * 3.17 + float(k) * 11.3;
        // each blob drifts around a spot near one of the edges
        float side = rand(vec2(s, 4.1)) * 6.2831853;
        vec2 home = vec2(cos(side), sin(side)) * asp * 0.55;
        vec2 at = home + vec2(wobble(t + float(k) * 1.7, s + 1.0), wobble(t * 0.8 + float(k) * 2.3, s + 2.0)) * 0.35 * asp;
        float r = 0.35 + 0.15 * wobble(t * 0.6, s + 3.0);
        vec2 d = p - at;
        float w = exp(-dot(d, d) / (r * r));
        float pulse = 0.75 + 0.25 * wobble(t * 1.3, s + 5.0);
        vec4 col = mix(color1, color2, float(k) / 2.0);
        light += col.rgb * col.a * w * pulse;
    }
    light = clamp(light * intensity, 0.0, 1.0) * c.a;
    return vec4(c.rgb + light - c.rgb * light, c.a);     // screen
}

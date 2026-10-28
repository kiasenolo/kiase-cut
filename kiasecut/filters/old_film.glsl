// @filter 老電影
// @category 風格
// @description 老舊的電影膠卷：泛黃、畫面跳動、亮度閃爍，有刮痕和灰塵
// @param amount float 1 0 1 "泛黃程度"
// @param scratches float 0.5 0 1 "刮痕"
// @param dust float 0.5 0 1 "灰塵"
// @param flicker float 0.4 0 1 "閃爍"
// @param jitter float 0.3 0 1 "跳動"
vec4 effect(vec2 uv) {
    float fr = floor(time * 24.0);                     // film frames, 24 a second
    vec2 asp = vec2(resolution.x / resolution.y, 1.0);
    vec2 at = uv + vec2(0.0, (rand(vec2(fr, 1.3)) - 0.5) * jitter * 8.0 / resolution.y);
    vec4 c = unpremultiply(src(at));

    float l = dot(c.rgb, vec3(0.299, 0.587, 0.114));
    vec3 rgb = mix(c.rgb, vec3(l) * vec3(1.07, 0.93, 0.72) + vec3(0.04, 0.02, 0.0), amount);
    rgb *= 1.0 + (rand(vec2(fr, 7.1)) - 0.5) * flicker * 0.35;
    vec2 d = (uv - 0.5) * asp;
    rgb *= 1.0 - 0.6 * smoothstep(0.35, 1.0, length(d));

    // scratches: up to three thin vertical lines, each staying a few frames
    for (int i = 0; i < 3; i++) {
        float life = floor(fr / (3.0 + float(i)));
        if (rand(vec2(life, float(i) + 3.3)) > scratches) continue;
        float x = rand(vec2(life, float(i) + 9.1)) + 0.02 * sin(uv.y * 7.0 + float(i));
        float w = (0.6 + rand(vec2(life, float(i))) * 1.2) / resolution.x;
        float line = 1.0 - smoothstep(w * 0.5, w * 1.5, abs(uv.x - x));
        line *= 0.5 + 0.5 * rand(vec2(floor(uv.y * 40.0), life));          // broken here and there
        rgb = mix(rgb, vec3(rand(vec2(life, 5.0)) < 0.5 ? 0.1 : 0.95), line * 0.7);
    }
    // dust: a few specks a frame
    vec2 cell = floor(uv * asp * 14.0);
    vec2 inside = fract(uv * asp * 14.0);
    if (rand(cell + fr * 1.37) < dust * 0.06) {
        vec2 at2 = vec2(rand(cell + fr), rand(cell + fr + 0.5)) * 0.6 + 0.2;
        float r = 0.04 + 0.12 * rand(cell + fr + 2.0);
        float speck = 1.0 - smoothstep(r * 0.6, r, length(inside - at2));
        rgb = mix(rgb, vec3(0.05), speck * 0.85);
    }
    return premultiply(vec4(clamp(rgb, 0.0, 1.0), c.a));
}

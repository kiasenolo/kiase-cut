// @filter 下雪
// @category 天氣
// @description 雪花飄落，遠近三層，會左右飄、可以被風吹
// @param amount float 0.5 0 1 "雪量"
// @param size float 8 1 40 "雪花大小"
// @param speed float 1 0 4 "速度"
// @param wind float 0.2 -2 2 "風"
// @param opacity float 0.9 0 1 "不透明度"
// @param color color #ffffff "顏色"

// one layer: a grid of cells, some holding a flake that drifts within it as the grid falls
float layer(vec2 p, float cells, float fall, float drift, float r, float seed) {
    vec2 q = p * cells + vec2(drift, -fall) * cells;
    vec2 cell = floor(q);
    float sum = 0.0;
    for (int j = -1; j <= 1; j++) {
        for (int i = -1; i <= 1; i++) {
            vec2 c = cell + vec2(float(i), float(j));
            if (rand(c + seed) > amount) continue;
            vec2 at = c + 0.5 + 0.35 * vec2(rand(c + seed + 1.3) * 2.0 - 1.0, rand(c + seed + 2.7) * 2.0 - 1.0);
            at.x += 0.3 * sin(time * (0.8 + rand(c + seed + 4.1)) + rand(c + seed) * 6.28);   // sway
            float rr = r * cells * (0.6 + 0.6 * rand(c + seed + 5.9));
            sum += 1.0 - smoothstep(rr * 0.4, rr, length(q - at));
        }
    }
    return sum;
}

vec4 effect(vec2 uv) {
    vec4 c = src(uv);
    vec2 p = vec2(uv.x * resolution.x / resolution.y, uv.y);
    float r = size / resolution.y;
    float t = time * speed;
    float s = layer(p, 14.0, t * 0.08, t * wind * 0.05, r * 0.5, 1.0) * 0.6
            + layer(p, 9.0, t * 0.13, t * wind * 0.08, r * 0.75, 2.0) * 0.8
            + layer(p, 5.0, t * 0.2, t * wind * 0.12, r, 3.0);
    float k = clamp(s, 0.0, 1.0) * opacity * color.a;
    return vec4(mix(c.rgb, color.rgb * c.a, k), c.a);
}

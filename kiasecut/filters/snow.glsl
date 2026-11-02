// @filter 下雪
// @category 天氣
// @description 雪花飄落，遠近三層，會左右飄、可以被風吹；從沒有雪開始下（時間偏移：開始時已經下了幾秒）
// @param amount float 0.5 0 4 "雪量"
// @param size float 8 1 40 "雪花大小"
// @param speed float 1 0 4 "速度"
// @param wind float 0.2 -2 2 "風"
// @param opacity float 0.9 0 1 "不透明度"
// @param color color #ffffff "顏色"
// @param time_offset float 0 0 120 "時間偏移（秒）"
// @param seed float 0 0 100 "種子"

// one layer: a grid of cells, each holding up to four flakes (雪量 above 1: more than one) that
// drift within it as the grid falls. Only flakes that were above the picture when the snow began
// are drawn, so it starts with an empty sky and fills as they fall in.
float layer(vec2 p, float cells, float fall, float drift, float r, float t, float salt) {
    vec2 q = p * cells + vec2(drift, -fall) * cells;
    vec2 cell = floor(q);
    float sum = 0.0;
    for (int j = -1; j <= 1; j++) {
        for (int i = -1; i <= 1; i++) {
            vec2 c = cell + vec2(float(i), float(j));
            for (int k = 0; k < 4; k++) {
                float have = amount - float(k);
                if (have <= 0.0) break;
                vec2 s = c + vec2(salt + seed * 7.31 + float(k) * 17.17, seed * 3.77 + float(k) * 5.53);
                if (rand(s) > have) continue;
                vec2 at = c + 0.5 + 0.35 * vec2(rand(s + 1.3) * 2.0 - 1.0, rand(s + 2.7) * 2.0 - 1.0);
                float rr = r * cells * (0.6 + 0.6 * rand(s + 5.9));
                if (at.y > -rr) continue;                 // in the picture before the snow began: not yet
                at.x += 0.3 * sin(t * (0.8 + rand(s + 4.1)) + rand(s) * 6.28);   // sway
                sum += 1.0 - smoothstep(rr * 0.4, rr, length(q - at));
            }
        }
    }
    return sum;
}

vec4 effect(vec2 uv) {
    vec4 c = src(uv);
    vec2 p = vec2(uv.x * resolution.x / resolution.y, uv.y);
    float r = size / resolution.y;
    float tt = time + time_offset;
    float t = tt * speed;
    float s = layer(p, 14.0, t * 0.08, t * wind * 0.05, r * 0.5, tt, 1.0) * 0.6
            + layer(p, 9.0, t * 0.13, t * wind * 0.08, r * 0.75, tt, 2.0) * 0.8
            + layer(p, 5.0, t * 0.2, t * wind * 0.12, r, tt, 3.0);
    float k = clamp(s, 0.0, 1.0) * opacity * color.a;
    return vec4(mix(c.rgb, color.rgb * c.a, k), c.a);
}

// @filter 漂浮光斑
// @category 粒子
// @description 大小不一的圓形（或多邊形）光斑在畫面上慢慢飄，一邊淡入淡出；遠近不同，對焦以外的光斑比較柔、比較小，邊緣可以比中間亮，像鏡頭失焦的光點
// @particles 5000 count
// @param count int 60 1 5000 "數量"
// @param life float 9 1 60 "壽命（秒）"
// @param life_var float 0.3 0 1 "壽命差異"
// @param time_offset float 0 0 120 "時間偏移（秒）"
// @panel 運動
// @param angle float 0 -360 360 "飄的方向（度，0 向上）"
// @param drift float 30 0 400 "飄的速度（像素／秒）"
// @param sway float 25 0 300 "左右搖擺（像素）"
// @param sway_speed float 0.5 0 5 "搖擺速度"
// @panel 外觀
// @param size float 120 4 600 "大小（像素，最近的）"
// @param blades int 0 0 12 "光圈葉片（0 是圓形）"
// @param blade_turn float 0 -180 180 "葉片角度（度）"
// @param colors gradient 0:#ffd9a0,0.25:#ffb36b,0.5:#ff8fa3,0.75:#fff2d0,1:#9fd8ff "顏色"
// @param brightness float 0.8 0 4 "亮度"
// @param rim float 0.6 0 1 "邊緣亮度"
// @param glow float 1 0 1 "發光（疊加）"
// @param twinkle float 0.3 0 1 "閃爍"
// @panel 景深
// @param depth float 0.7 0 1 "遠近差異"
// @param focus float 0.6 0 1 "對焦位置（0 遠、1 近）"
// @param blur float 0.8 0 1 "失焦柔化"
// @param seed float 0 0 100 "種子"
// @step 10 drift sway

// Stateless (see sparks.glsl): spot i is a slot born again every `life` seconds, staggered by i / count, each time somewhere
// else on the picture; it drifts, fades in and out. Each has a depth z (0 far, 1 near): near ones are bigger and faster, and
// the further from the focus a spot is, the softer its edge.

float R(int i, float k, float salt) {
    return rand(vec2(float(i) * 0.6180339 + seed * 3.7 + salt * 11.3, k * 1.7321 + salt * 5.11 + 0.5));
}

bool particle(int i, out Particle p) {
    float s = time + time_offset - float(i) * life / float(count);
    if (s < 0.0) return false;
    float k = floor(s / life);
    s -= k * life;
    float lf = life * (1.0 - life_var * R(i, k, 1.0));
    if (s >= lf) return false;
    float u = s / lf;

    float z = R(i, k, 2.0);
    float a = radians(angle);
    vec2 dir = vec2(sin(a), -cos(a));
    vec2 pos = vec2(R(i, k, 3.0), R(i, k, 4.0)) * resolution + dir * drift * (0.4 + 1.2 * z) * s;
    pos += sway * (0.5 + R(i, k, 5.0)) * vec2(sin(s * sway_speed * (0.7 + 0.6 * R(i, k, 6.0)) + 6.2831853 * R(i, k, 7.0)),
                                              cos(s * sway_speed * (0.5 + 0.6 * R(i, k, 8.0)) + 6.2831853 * R(i, k, 9.0)));

    float r = size * 0.5 * mix(1.0 - depth * 0.75, 1.0, z) * (0.8 + 0.4 * R(i, k, 10.0));
    float soft = clamp(0.06 + abs(z - focus) * 2.0 * blur * 0.9, 0.0, 1.0);
    p.pos = pos;
    p.size = vec2(r);
    p.rot = radians(blade_turn);

    float fade = smoothstep(0.0, 0.2, u) * (1.0 - smoothstep(0.75, 1.0, u));
    float tw = 1.0 - twinkle * (0.5 + 0.5 * sin(time * (0.8 + 2.0 * R(i, k, 11.0)) + 40.0 * R(i, k, 12.0)));
    vec4 c = gradient_eval(colors_p, colors_c, colors_n, R(i, k, 13.0), 2, 0, 0);
    c.rgb *= brightness * tw;
    c.a *= fade * (0.5 + 0.5 * (1.0 - abs(z - focus)));                    // (the ones out of focus are fainter)
    p.color = c;
    p.data = vec4(max(soft, 1.5 / max(r, 1.0)), 0.0, 0.0, 0.0);
    return true;
}

vec4 sprite(vec2 q, vec4 color, vec4 data) {
    float d = length(q);
    if (blades >= 3) {                                                    // a polygon: the distance in units of its edge
        float seg = 6.2831853 / float(blades);
        float t = mod(atan(q.y, q.x) + 6.2831853, seg) - 0.5 * seg;
        d /= cos(0.5 * seg) / cos(t);
    }
    float soft = data.x;
    float disc = 1.0 - smoothstep(1.0 - soft, 1.0, d);
    float ring = rim * (1.0 - soft) * smoothstep(0.6, 0.95, d);
    float a = disc * (1.0 - 0.6 * rim + ring * 1.3);
    return vec4(color.rgb * color.a * a, color.a * a * (1.0 - glow));
}

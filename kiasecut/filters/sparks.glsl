// @filter 火花
// @category 粒子
// @nodes
// @description 從一點噴出的火花：有重力和空氣阻力，沿著運動方向拉出拖尾，顏色從亮到暗；可以持續噴，也可以一次爆發（煙火）
// @particles 20000 count
// @param count int 600 1 20000 "粒子數"
// @param mode menu 持續 "持續|爆發" "方式"
// @param life float 1.5 0.1 10 "壽命（秒）"
// @param life_var float 0.4 0 1 "壽命差異"
// @param period float 3 0.2 30 "爆發間隔（秒）"
// @enable period mode == 爆發
// @panel 發射
// @param origin vec2 0.5,0.6 -1 2 "位置"
// @param radius float 0 0 500 "發射範圍（像素）"
// @param angle float 0 -360 360 "方向（度，0 向上）"
// @param spread float 360 0 360 "散開角度"
// @param speed float 500 0 3000 "初速（像素／秒）"
// @param speed_var float 0.6 0 1 "初速差異"
// @panel 力
// @param gravity float 700 -3000 3000 "重力（像素／秒²）"
// @param drag float 0.8 0 10 "空氣阻力"
// @param wind float 0 -2000 2000 "風（像素／秒²）"
// @panel 外觀
// @param size float 3 0.5 40 "大小（像素）"
// @param streak float 0.05 0 0.3 "拖尾（秒）"
// @param color color #ffd27a "起始顏色"
// @param color_end color #ff3a10 "結束顏色"
// @param brightness float 1.5 0 10 "亮度"
// @param glow float 1 0 1 "發光（疊加）"
// @param flicker float 0.5 0 1 "閃爍"
// @param seed float 0 0 100 "種子"
// @step 10 radius speed gravity wind

// Nothing is kept from one frame to the next: where a spark is follows from its number, the time and the settings, so any
// frame (a jump on the timeline, the export) is drawn on its own. Spark i is a slot that is born again every `life` seconds
// (staggered by i / count, so there is a steady stream) or, as a burst, all of them together every `period` seconds.

// a random number 0 - 1 for spark i, its k-th birth, and what it is for (salt)
float R(int i, float k, float salt) {
    return rand(vec2(float(i) * 0.6180339 + seed * 3.7 + salt * 11.3, k * 1.7321 + salt * 5.11 + 0.5));
}

bool particle(int i, out Particle p) {
    float n = float(count);
    float s, k;
    if (mode == 0) {
        s = time - float(i) * life / n;
        if (s < 0.0) return false;
        k = floor(s / life);
        s -= k * life;
    } else {
        k = floor(time / period);
        s = time - k * period;
    }
    float lf = life * (1.0 - life_var * R(i, k, 1.0));
    if (s >= lf) return false;
    float u = s / lf;                                           // 0 at birth, 1 at death

    float a = radians(angle + (R(i, k, 2.0) - 0.5) * spread);
    vec2 v0 = vec2(sin(a), -cos(a)) * speed * (1.0 - speed_var * R(i, k, 3.0));
    vec2 acc = vec2(wind, gravity);
    vec2 pos, vel;
    if (drag > 0.001) {                                         // v' = acc - drag v
        vec2 vt = acc / drag;
        float e = exp(-drag * s);
        vel = vt + (v0 - vt) * e;
        pos = vt * s + (v0 - vt) * (1.0 - e) / drag;
    } else {
        vel = v0 + acc * s;
        pos = v0 * s + 0.5 * acc * s * s;
    }
    float ea = R(i, k, 4.0) * 6.2831853;
    pos += origin * resolution + radius * sqrt(R(i, k, 5.0)) * vec2(cos(ea), sin(ea));

    float sz = size * (1.0 - 0.6 * u);
    float speed_now = length(vel);
    float half_len = sz + 0.5 * speed_now * streak;             // the head is where the spark is, the tail trails behind it
    vec2 heading = speed_now > 0.001 ? vel / speed_now : vec2(1.0, 0.0);
    p.pos = pos - heading * (half_len - sz);
    p.size = vec2(half_len, sz);
    p.rot = atan(heading.y, heading.x);

    float f = 1.0 - flicker * (0.5 + 0.5 * sin(time * (25.0 + 20.0 * R(i, k, 6.0)) + 50.0 * R(i, k, 7.0)));
    vec4 c = mix(color, color_end, pow(u, 0.7));
    c.rgb *= brightness * f;
    c.a *= 1.0 - u * u;
    p.color = c;
    p.data = vec4(u, 0.0, 0.0, 0.0);
    return true;
}

vec4 sprite(vec2 q, vec4 color, vec4 data) {
    float across = 1.0 - smoothstep(0.0, 1.0, abs(q.y));
    across *= across;
    float along = mix(0.25, 1.0, smoothstep(-1.0, 1.0, q.x) * smoothstep(-1.0, 1.0, q.x));      // dim tail, bright head
    float ends = smoothstep(-1.0, -0.6, q.x) * (1.0 - smoothstep(0.75, 1.0, q.x));
    float a = across * along * ends;
    return vec4(color.rgb * color.a * a, color.a * a * (1.0 - glow));
}

// @filter 紙屑／彩帶
// @category 粒子
// @description 彩色紙屑或彩帶：從上面飄落，或從一點噴出再慢慢落下；紙片翻面時變窄、變暗，彩帶會扭動。顏色從漸變裡隨機挑
// @particles 20000 count
// @param count int 300 1 20000 "數量"
// @param mode menu 飄落 "飄落|噴發" "方式"
// @param shape menu 紙屑 "紙屑|彩帶" "形狀"
// @param life float 6 0.5 30 "壽命（秒）"
// @param life_var float 0.3 0 1 "壽命差異"
// @param period float 6 0.5 60 "噴發間隔（秒）"
// @enable period mode == 噴發
// @param time_offset float 0 0 120 "時間偏移（秒）"
// @panel 發射
// @param origin vec2 0.5,1 -1 2 "噴發位置"
// @param angle float 0 -360 360 "噴發方向（度，0 向上）"
// @param spread float 60 0 360 "散開角度"
// @param speed float 900 0 4000 "初速（像素／秒）"
// @param speed_var float 0.5 0 1 "初速差異"
// @enable origin mode == 噴發
// @enable angle mode == 噴發
// @enable spread mode == 噴發
// @enable speed mode == 噴發
// @enable speed_var mode == 噴發
// @panel 力
// @param gravity float 300 -3000 3000 "重力（像素／秒²）"
// @param drag float 1.5 0 10 "空氣阻力"
// @param wind float 0 -2000 2000 "風（像素／秒²）"
// @param sway float 40 0 400 "左右搖擺（像素）"
// @param sway_speed float 2 0 10 "搖擺速度"
// @panel 外觀
// @param size float 10 1 80 "大小（像素）"
// @param aspect float 1.6 1 8 "長寬比"
// @param spin float 4 0 30 "旋轉速度"
// @param flip float 6 0 30 "翻面速度"
// @param shade float 0.6 0 1 "翻面明暗"
// @param colors gradient 0:#ff4d6d,0.2:#ffd166,0.4:#06d6a0,0.6:#4cc9f0,0.8:#b388ff "顏色"
// @param seed float 0 0 100 "種子"
// @step 10 speed gravity wind sway

// Nothing is kept from one frame to the next (see sparks.glsl): where a piece is follows from its number, the time and the
// settings. Piece i is a slot born again every `life` seconds, staggered by i / count (飄落) or, as a burst, all together
// every `period` seconds (噴發). It moves as v' = acceleration - drag v (so it settles to a terminal speed gravity / drag) and
// sways to the side; a paper piece turns about its centre and flips (its height shrinks with cos of the flip), a ribbon waves.

// a random number 0 - 1 for piece i, its k-th birth, and what it is for (salt)
float R(int i, float k, float salt) {
    return rand(vec2(float(i) * 0.6180339 + seed * 3.7 + salt * 11.3, k * 1.7321 + salt * 5.11 + 0.5));
}

bool particle(int i, out Particle p) {
    float n = float(count);
    float tt = time + time_offset;
    float s, k;
    if (mode == 0) {
        s = tt - float(i) * life / n;
        if (s < 0.0) return false;
        k = floor(s / life);
        s -= k * life;
    } else {
        k = floor(tt / period);
        s = tt - k * period;
    }
    float lf = life * (1.0 - life_var * R(i, k, 1.0));
    if (s >= lf) return false;
    float u = s / lf;

    vec2 v0, at;
    if (mode == 0) {
        v0 = vec2(0.0);
        at = vec2((R(i, k, 2.0) * 1.2 - 0.1) * resolution.x, -size * 3.0);      // along the top, a little past both sides
    } else {
        float a = radians(angle + (R(i, k, 2.0) - 0.5) * spread);
        v0 = vec2(sin(a), -cos(a)) * speed * (1.0 - speed_var * R(i, k, 3.0));
        at = origin * resolution;
    }
    vec2 acc = vec2(wind, gravity);
    vec2 pos;
    if (drag > 0.001) {
        vec2 vt = acc / drag;
        pos = vt * s + (v0 - vt) * (1.0 - exp(-drag * s)) / drag;
    } else {
        pos = v0 * s + 0.5 * acc * s * s;
    }
    pos += at;
    pos.x += sway * (0.5 + R(i, k, 4.0)) * sin(s * sway_speed * (0.7 + 0.6 * R(i, k, 5.0)) + 6.2831853 * R(i, k, 6.0));

    float sz = size * (0.7 + 0.3 * R(i, k, 7.0));
    float turn = R(i, k, 8.0) * 6.2831853 + spin * s * (R(i, k, 9.0) * 2.0 - 1.0);
    float facing = cos(R(i, k, 10.0) * 6.2831853 + flip * s * (0.5 + R(i, k, 11.0)));
    p.pos = pos;
    p.rot = turn;
    if (shape == 0) {
        p.size = vec2(sz * 0.5 * aspect, sz * 0.5 * max(abs(facing), 0.08));
    } else {
        p.size = vec2(sz * aspect * 2.0, sz);
        facing = 1.0;
    }
    vec4 c = gradient_eval(colors_p, colors_c, colors_n, R(i, k, 12.0), 4, 0, 0);
    c.a *= 1.0 - smoothstep(0.9, 1.0, u);
    p.color = c;
    p.data = vec4(facing, time * 3.0 + R(i, k, 13.0) * 6.2831853, 1.2 / max(p.size.x, 1.0), 1.2 / max(p.size.y, 1.0));
    return true;
}

vec4 sprite(vec2 q, vec4 color, vec4 data) {
    float a, light;
    if (shape == 0) {
        vec2 e = (1.0 - abs(q)) / data.zw;                         // soft edges, about a pixel wide
        a = clamp(min(e.x, e.y), 0.0, 1.0);
        light = (data.x > 0.0 ? 1.0 : 0.72) * mix(1.0, abs(data.x), shade * 0.5);
    } else {
        float ph = q.x * 3.0 + data.y;
        float d = abs(q.y - 0.45 * sin(ph));
        a = clamp((0.3 - d) / data.w, 0.0, 1.0) * clamp((1.0 - abs(q.x)) / data.z, 0.0, 1.0);
        light = 1.0 - shade * 0.35 * (0.5 - 0.5 * cos(ph));
    }
    return vec4(color.rgb * light * color.a * a, color.a * a);
}

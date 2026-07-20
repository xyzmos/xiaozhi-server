import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.springframework.data.redis.serializer.RedisSerializer;

import cn.hutool.json.JSONObject;
import xiaozhi.modules.model.entity.ModelConfigEntity;
import xiaozhi.modules.sys.vo.SysDictDataItem;
import xiaozhi.modules.timbre.vo.TimbreDetailsVO;

public final class RedisCodecVectors {
    private RedisCodecVectors() {}

    private static void vector(String name, Object value) {
        RedisSerializer<Object> serializer = RedisSerializer.json();
        byte[] bytes = serializer.serialize(value);
        Object decoded = serializer.deserialize(bytes);
        System.out.println(name + "\t" + new String(bytes, StandardCharsets.UTF_8)
                + "\t" + (decoded == null ? "null" : decoded.getClass().getName()));
    }

    public static void main(String[] args) {
        vector("string", "hello");
        vector("integer", Integer.valueOf(7));
        vector("long", Long.valueOf(2147483648L));
        vector("boolean", Boolean.TRUE);

        Map<String, Object> map = new HashMap<>();
        map.put("text", "hello");
        map.put("number", Long.valueOf(2147483648L));
        map.put("list", new ArrayList<>(List.of("a", "b")));
        Map<String, Object> nested = new HashMap<>();
        nested.put("enabled", Boolean.TRUE);
        map.put("nested", nested);
        vector("map", map);
        vector("list", new ArrayList<>(List.of("a", Long.valueOf(2147483648L), nested)));
        vector("date", new Date(0));

        TimbreDetailsVO timbre = new TimbreDetailsVO();
        timbre.setId("voice-1");
        timbre.setName("sample");
        timbre.setSort(2L);
        vector("pojo", timbre);

        ModelConfigEntity model = new ModelConfigEntity();
        model.setId("model-1");
        model.setModelType("LLM");
        JSONObject config = new JSONObject();
        config.set("type", "openai");
        config.set("api_key", "secret");
        model.setConfigJson(config);
        vector("model-pojo", model);

        SysDictDataItem item = new SysDictDataItem();
        item.setName("China");
        item.setKey("+86");
        vector("dict-list", new ArrayList<>(List.of(item)));
    }
}

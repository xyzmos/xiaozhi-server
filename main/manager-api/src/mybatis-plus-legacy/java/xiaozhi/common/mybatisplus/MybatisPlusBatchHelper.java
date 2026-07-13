package xiaozhi.common.mybatisplus;

import java.util.Collection;
import java.util.function.BiConsumer;

import org.apache.ibatis.logging.Log;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;

import com.baomidou.mybatisplus.extension.toolkit.SqlHelper;

/**
 * Type-safe access to the MyBatis-Plus 3.5.5/3.5.6 batch callback API.
 */
public final class MybatisPlusBatchHelper {
    private MybatisPlusBatchHelper() {
    }

    @SuppressWarnings("deprecation")
    public static <E> boolean executeBatch(SqlSessionFactory sqlSessionFactory, Log log, Collection<E> entities,
            int batchSize, BiConsumer<SqlSession, E> operation) {
        return SqlHelper.executeBatch(sqlSessionFactory, log, entities, batchSize, operation);
    }
}

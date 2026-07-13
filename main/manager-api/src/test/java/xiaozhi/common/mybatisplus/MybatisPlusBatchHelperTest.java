package xiaozhi.common.mybatisplus;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.ArrayList;
import java.util.List;

import org.apache.ibatis.executor.BatchResult;
import org.apache.ibatis.logging.Log;
import org.apache.ibatis.mapping.MappedStatement;
import org.apache.ibatis.session.ExecutorType;
import org.apache.ibatis.session.SqlSession;
import org.apache.ibatis.session.SqlSessionFactory;
import org.junit.jupiter.api.Test;

class MybatisPlusBatchHelperTest {

    @Test
    void executesBatchThroughSelectedVersionAdapter() {
        SqlSessionFactory sqlSessionFactory = mock(SqlSessionFactory.class);
        SqlSession sqlSession = mock(SqlSession.class);
        Log log = mock(Log.class);
        when(sqlSessionFactory.openSession(ExecutorType.BATCH)).thenReturn(sqlSession);

        BatchResult batchResult = new BatchResult(mock(MappedStatement.class), "INSERT");
        batchResult.setUpdateCounts(new int[] { 1, 1 });
        when(sqlSession.flushStatements()).thenReturn(List.of(batchResult));

        List<String> processed = new ArrayList<>();
        boolean result = MybatisPlusBatchHelper.executeBatch(sqlSessionFactory, log, List.of("first", "second"), 2,
                (session, entity) -> {
                    assertSame(sqlSession, session);
                    processed.add(entity);
                });

        assertTrue(result);
        assertEquals(List.of("first", "second"), processed);
        verify(sqlSession).flushStatements();
        verify(sqlSession).commit(true);
        verify(sqlSession).close();
    }
}

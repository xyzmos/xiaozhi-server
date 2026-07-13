package xiaozhi.common.mybatisplus;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;

/**
 * Stable project-level base class for the MyBatis-Plus 3.5.17 Spring service implementation.
 */
public class MpServiceImpl<M extends BaseMapper<T>, T>
        extends com.baomidou.mybatisplus.spring.service.impl.ServiceImpl<M, T> implements MpService<T> {
}

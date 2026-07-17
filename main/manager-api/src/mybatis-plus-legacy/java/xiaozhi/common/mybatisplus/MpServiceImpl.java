package xiaozhi.common.mybatisplus;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;

/**
 * Stable project-level base class for the MyBatis-Plus 3.5.5/3.5.6 service implementation.
 */
public class MpServiceImpl<M extends BaseMapper<T>, T>
        extends com.baomidou.mybatisplus.extension.service.impl.ServiceImpl<M, T> implements MpService<T> {
}

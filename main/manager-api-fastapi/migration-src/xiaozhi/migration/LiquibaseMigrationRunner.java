package xiaozhi.migration;

import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;

import javax.sql.DataSource;

import liquibase.integration.spring.SpringLiquibase;
import org.springframework.core.io.DefaultResourceLoader;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

/** Runs only the original Spring Liquibase changelog; it never starts manager-api or Redis. */
public final class LiquibaseMigrationRunner {
    private LiquibaseMigrationRunner() {
    }

    public static void main(String[] args) throws Exception {
        String url = requiredEnvironment("MIGRATION_JDBC_URL");
        String username = requiredEnvironment("MIGRATION_USERNAME");
        String password = requiredEnvironment("MIGRATION_PASSWORD");

        DriverManagerDataSource dataSource = new DriverManagerDataSource(url, username, password);
        dataSource.setDriverClassName("com.mysql.cj.jdbc.Driver");
        runLiquibase(dataSource);
        System.out.println("Liquibase migration complete; applied changeSets=" + appliedChangeSetCount(dataSource));
    }

    private static void runLiquibase(DataSource dataSource) throws Exception {
        SpringLiquibase liquibase = new SpringLiquibase();
        liquibase.setDataSource(dataSource);
        liquibase.setChangeLog("classpath:db/changelog/db.changelog-master.yaml");
        liquibase.setResourceLoader(new DefaultResourceLoader(Thread.currentThread().getContextClassLoader()));
        liquibase.setDropFirst(false);
        liquibase.setShouldRun(true);
        liquibase.afterPropertiesSet();
    }

    private static int appliedChangeSetCount(DataSource dataSource) throws Exception {
        try (Connection connection = dataSource.getConnection();
                Statement statement = connection.createStatement();
                ResultSet result = statement.executeQuery("SELECT COUNT(*) FROM DATABASECHANGELOG")) {
            if (!result.next()) {
                throw new IllegalStateException("DATABASECHANGELOG count query returned no row");
            }
            return result.getInt(1);
        }
    }

    private static String requiredEnvironment(String name) {
        String value = System.getenv(name);
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("Required environment variable is missing: " + name);
        }
        return value;
    }
}

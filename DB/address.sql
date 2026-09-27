-- users 테이블에 사용자의 기본 배달 주소를 저장할 컬럼 추가
ALTER TABLE users
ADD COLUMN address VARCHAR(255);

DESCRIBE users;